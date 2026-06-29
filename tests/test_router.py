"""Tests for ToolRouter — parallel search, no fallback, extract chain, envelopes."""

from __future__ import annotations

import asyncio

from hermes_web_tools.backends.base import ExtractItem, SearchItem
from hermes_web_tools.config import Config
from hermes_web_tools.router import ToolRouter, _extract_items_to_dicts


def run(coro):
    return asyncio.run(coro)


def cfg(**flags):
    c = Config()
    c.max_urls = 3
    c.max_content_chars = 10
    c.max_total_chars = 15
    if flags.get("exa"):
        c.exa_api_key = "exa"
    if flags.get("tavily"):
        c.tavily_keys = ["t"]
    if flags.get("grok"):
        c.grok_api_url = "https://grok"
        c.grok_api_key = "g"
    if flags.get("firecrawl"):
        c.firecrawl_api_key = "f"
    if flags.get("mineru"):
        c.mineru_api_token = "m"
    return c


class FakeExa:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def search(self, query, limit=5, category=None, search_type="auto", **kw):
        self.calls.append((query, limit, category, search_type))
        if self.fail:
            raise RuntimeError("exa bad")
        return [SearchItem("Exa", "https://exa.com/a", "d", "exa", 1)]

    async def context(self, query, max_tokens=None):
        self.calls.append(("context", query, max_tokens))
        return {"code_context": "code", "results_count": 2, "metadata": {}}

    async def answer(self, query, text=True):
        self.calls.append(("answer", query, text))
        return {"answer": "a", "citations": []}


class FakeTavily:
    def __init__(self, fail=False, should_not_call=False):
        self.calls = []
        self.fail = fail
        self.should_not_call = should_not_call

    def available(self):
        return True

    async def search(self, query, limit=5, search_depth="basic"):
        if self.should_not_call:
            raise AssertionError("tavily should not be called")
        self.calls.append((query, limit, search_depth))
        if self.fail:
            raise RuntimeError("tavily bad")
        return [SearchItem("Tav", "https://tav.com/a", "d", "tavily", 1)]

    async def extract(self, urls):
        self.calls.append(("extract", urls))
        return [ExtractItem(url=urls[0], content="tavily", raw_content="tavily")]


class FakeGrok:
    def __init__(self):
        self.calls = []

    async def search(self, query, limit=5):
        self.calls.append((query, limit))
        return [SearchItem("Grok", "https://x.com/a", "d", "grok", 1)]


class FakeExtractor:
    def __init__(self, name, available=True, error="", content="ok"):
        self.name = name
        self._available = available
        self.error = error
        self.content = content
        self.calls = []

    def available(self):
        return self._available

    async def extract(self, urls):
        self.calls.append(urls)
        return [
            ExtractItem(
                url=urls[0], content=self.content, raw_content=self.content, error=self.error
            )
        ]


def test_web_search_parallel_merges_successes():
    r = ToolRouter(cfg(exa=True, tavily=True), exa=FakeExa(), tavily=FakeTavily())
    out = run(r.web_search("q", limit=5))
    assert out["success"] is True
    assert len(out["data"]["web"]) == 2
    assert {w["metadata"]["sources"][0] for w in out["data"]["web"]} == {"exa", "tavily"}


def test_web_search_skips_failed_provider_no_extra_fallback():
    tav = FakeTavily(fail=True)
    r = ToolRouter(cfg(exa=True, tavily=True), exa=FakeExa(), tavily=tav)
    out = run(r.web_search("q", limit=5))
    assert out["success"] is True
    assert [w["url"] for w in out["data"]["web"]] == ["https://exa.com/a"]
    assert out["metadata"]["errors"]["tavily"] == "tavily bad"
    assert len(tav.calls) == 1  # no extra fallback call


def test_all_failed_search_returns_error():
    r = ToolRouter(cfg(exa=True), exa=FakeExa(fail=True))
    out = run(r.web_search("q"))
    assert out["success"] is False
    assert "all providers failed" in out["error"]


def test_realtime_uses_grok_and_exa_not_tavily_even_if_configured():
    exa = FakeExa()
    grok = FakeGrok()
    r = ToolRouter(
        cfg(exa=True, tavily=True, grok=True),
        exa=exa,
        grok=grok,
        tavily=FakeTavily(should_not_call=True),
    )
    out = run(r.web_search_realtime("now", limit=3))
    assert out["success"] is True
    assert exa.calls[0][2] == "news"
    assert grok.calls


def test_research_sets_exa_research_and_deep():
    exa = FakeExa()
    r = ToolRouter(cfg(exa=True), exa=exa)
    run(r.web_search_research("paper", limit=4))
    assert exa.calls[0] == ("paper", 4, "research paper", "deep")


def test_entities_maps_entity_type():
    exa = FakeExa()
    r = ToolRouter(cfg(exa=True), exa=exa)
    run(r.web_search_entities("earnings", entity_type="financial"))
    assert exa.calls[0][2] == "financial report"


def test_code_and_answer_envelopes():
    exa = FakeExa()
    r = ToolRouter(cfg(exa=True), exa=exa)
    assert run(r.web_search_code("hooks"))["data"]["code_context"] == "code"
    assert run(r.web_answer("what?"))["data"]["answer"] == "a"


def test_extract_max_urls():
    r = ToolRouter(cfg())
    out = run(r.web_extract(["https://a.com", "https://b.com", "https://c.com", "https://d.com"]))
    assert out["success"] is False
    assert "too many" in out["error"]


def test_extract_document_chain_mineru_fail_then_firecrawl(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.router.validate_url", lambda url: None)
    mineru = FakeExtractor("mineru", error="bad")
    fire = FakeExtractor("firecrawl", content="fire")
    r = ToolRouter(cfg(mineru=True, firecrawl=True), mineru=mineru, firecrawl=fire)
    out = run(r.web_extract(["https://e.com/a.pdf"]))
    assert out["data"][0]["content"] == "fire"
    assert mineru.calls and fire.calls


def test_extract_truncates(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.router.validate_url", lambda url: None)
    fire = FakeExtractor("firecrawl", content="abcdefghijklmnopqrstuvwxyz")
    r = ToolRouter(cfg(firecrawl=True), firecrawl=fire)
    out = run(r.web_extract(["https://e.com/page"]))
    item = out["data"][0]
    assert item["content"] == "abcdefghij"
    assert item["metadata"]["truncated"] is True
    assert item["metadata"]["content_truncated"] is True
    assert item["metadata"]["raw_truncated"] is True


def test_extract_raw_content_respects_total_budget():
    c = cfg()
    c.max_content_chars = 10
    c.max_total_chars = 15
    out = _extract_items_to_dicts(
        [
            ExtractItem(url="https://e.com/1", content="abcdefghij", raw_content="ABCDEFGHIJ"),
            ExtractItem(url="https://e.com/2", content="klmnopqrst", raw_content="KLMNOPQRST"),
        ],
        c,
    )
    assert out[0]["raw_content"] == "ABCDE"
    assert out[1]["content"] == "klmno"
    assert out[1]["raw_content"] == ""
