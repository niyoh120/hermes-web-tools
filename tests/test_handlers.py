"""Tests for handlers — argument validation, clamping, check_fn availability."""

from __future__ import annotations

import asyncio
import json

from hermes_web_tools import handlers


def run(coro):
    return asyncio.run(coro)


class FakeRouter:
    def __init__(self):
        self.calls = []

    async def web_search(self, query, limit=5):
        self.calls.append(("web_search", query, limit))
        return {"success": True, "data": {"web": []}}

    async def web_search_realtime(self, query, limit=5):
        self.calls.append(("realtime", query, limit))
        return {"success": True, "data": {"web": []}}

    async def web_search_research(self, query, limit=5):
        self.calls.append(("research", query, limit))
        return {"success": True, "data": {"web": []}}

    async def web_search_code(self, query, max_tokens=None):
        self.calls.append(("code", query, max_tokens))
        return {"success": True, "data": {"code_context": "c"}}

    async def web_search_entities(self, query, limit=5, entity_type="auto"):
        self.calls.append(("entities", query, limit, entity_type))
        return {"success": True, "data": {"web": []}}

    async def web_answer(self, query, text=True):
        self.calls.append(("answer", query, text))
        return {"success": True, "data": {"answer": "a"}}

    async def web_extract(self, urls):
        self.calls.append(("extract", urls))
        return {"success": True, "data": []}


def patch_router(monkeypatch):
    fake = FakeRouter()
    monkeypatch.setattr(handlers, "_router", lambda: fake)
    return fake


def decode(s):
    return json.loads(s)


def test_web_search_clamps_limit(monkeypatch):
    fake = patch_router(monkeypatch)
    out = decode(run(handlers.web_search({"query": " q ", "limit": 999})))
    assert out["success"] is True
    assert fake.calls == [("web_search", "q", 100)]


def test_web_search_default_limit(monkeypatch):
    fake = patch_router(monkeypatch)
    run(handlers.web_search({"query": "q"}))
    assert fake.calls == [("web_search", "q", 5)]


def test_missing_query_returns_error():
    out = decode(run(handlers.web_search({"query": ""})))
    assert out["success"] is False
    assert "query" in out["error"]


def test_code_max_tokens_clamp(monkeypatch):
    fake = patch_router(monkeypatch)
    out = decode(run(handlers.web_search_code({"query": "q", "max_tokens": 1_000_000})))
    assert out["success"] is True
    assert fake.calls == [("code", "q", 100_000)]


def test_entities_entity_type(monkeypatch):
    fake = patch_router(monkeypatch)
    run(handlers.web_search_entities({"query": "q", "entity_type": "financial", "limit": 2}))
    assert fake.calls == [("entities", "q", 2, "financial")]


def test_answer_text_bool(monkeypatch):
    fake = patch_router(monkeypatch)
    run(handlers.web_answer({"query": "q", "text": False}))
    assert fake.calls == [("answer", "q", False)]


def test_handler_internal_error_is_sanitized(monkeypatch):
    class BoomRouter(FakeRouter):
        async def web_search(self, query, limit=5):
            raise RuntimeError("token=secret")

    monkeypatch.setattr(handlers, "_router", lambda: BoomRouter())
    out = decode(run(handlers.web_search({"query": "q"})))
    assert out == {"success": False, "error": "web_search: internal error"}


def test_extract_validates_urls_list(monkeypatch):
    fake = patch_router(monkeypatch)
    out = decode(run(handlers.web_extract({"urls": [" https://e.com ", 3, ""]})))
    assert out["success"] is True
    assert fake.calls == [("extract", ["https://e.com"])]


def test_extract_rejects_empty_urls():
    assert decode(run(handlers.web_extract({"urls": []})))["success"] is False
    assert decode(run(handlers.web_extract({"urls": [3]})))["success"] is False


def test_check_fns(monkeypatch):
    for var in [
        "EXA_API_KEY",
        "TAVILY_API_KEY",
        "GROK_API_URL",
        "GROK_API_KEY",
        "FIRECRAWL_API_KEY",
        "MINERU_API_TOKEN",
        "MINERU_AGENT_FALLBACK_ENABLED",
    ]:
        monkeypatch.delenv(var, raising=False)
    assert handlers.check_web_search() is False
    assert handlers.check_web_search_realtime() is False
    assert handlers.check_web_extract() is False

    monkeypatch.setenv("TAVILY_API_KEY", "t")
    assert handlers.check_web_search() is True
    assert handlers.check_web_search_research() is True
    assert handlers.check_web_search_entities() is True
    assert handlers.check_web_search_realtime() is False  # no Tavily fallback
    assert handlers.check_web_extract() is True

    monkeypatch.setenv("EXA_API_KEY", "e")
    assert handlers.check_web_search_code() is True
    assert handlers.check_web_answer() is True
    assert handlers.check_web_search_realtime() is False

    monkeypatch.setenv("GROK_API_URL", "https://grok.local")
    monkeypatch.setenv("GROK_API_KEY", "g")
    assert handlers.check_web_search_realtime() is True
