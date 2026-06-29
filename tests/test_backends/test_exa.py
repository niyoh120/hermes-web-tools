"""Tests for Exa backend — search/context/answer/extract via MockTransport."""

from __future__ import annotations

import json

import httpx

from hermes_web_tools.backends import base
from hermes_web_tools.backends.exa import ExaBackend
from hermes_web_tools.config import load_config


def run(coro):
    import asyncio

    return asyncio.run(coro)


def _cfg(monkeypatch, **kw):
    monkeypatch.setenv("EXA_API_KEY", "k")
    cfg = load_config()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _backend(handler, cfg):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ExaBackend(cfg, client=client)


def test_search_normalizes_results(monkeypatch):
    seen = {}

    def handler(req):
        seen["path"] = str(req.url)
        seen["auth"] = req.headers.get("x-api-key")
        seen["body"] = req.content
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "T1", "url": "https://e.com/a", "highlights": ["h"]},
                    {"title": "T2", "url": "https://e.com/b", "summary": "s"},
                ]
            },
        )

    cfg = _cfg(monkeypatch)
    cfg.exa_base_url = "https://exa.local"
    be = _backend(handler, cfg)
    items = run(be.search("q", limit=5, category="news"))
    assert seen["path"] == "https://exa.local/search"
    assert seen["auth"] == "k"
    assert len(items) == 2
    assert items[0].title == "T1" and items[0].provider == "exa" and items[0].position == 1
    assert items[0].description == "h"
    assert items[1].description == "s"
    assert json.loads(seen["body"])["category"] == "news"


def test_search_auto_category_omitted(monkeypatch):
    seen = {}

    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"results": []})

    be = _backend(handler, _cfg(monkeypatch))
    run(be.search("q"))
    assert b"category" not in seen["body"]


def test_context_envelope(monkeypatch):
    def handler(req):
        assert str(req.url) == "https://api.exa.ai/context"
        return httpx.Response(200, json={"response": "// code", "resultsCount": 7})

    be = _backend(handler, _cfg(monkeypatch))
    out = run(be.context("hooks", max_tokens=5000))
    assert out["code_context"] == "// code"
    assert out["results_count"] == 7


def test_answer_normalizes_citations(monkeypatch):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "answer": "Paris",
                "citations": [{"title": "Wiki", "url": "https://w/x", "text": "t"}],
            },
        )

    be = _backend(handler, _cfg(monkeypatch))
    out = run(be.answer("capital of france?"))
    assert out["answer"] == "Paris"
    assert out["citations"] == [{"title": "Wiki", "url": "https://w/x", "content": "t"}]


def test_extract(monkeypatch):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://e.com/a", "title": "A", "text": "body"},
                ],
                "statuses": [
                    {"id": "https://e.com/bad", "success": False, "error": "blocked"},
                ],
            },
        )

    be = _backend(handler, _cfg(monkeypatch))
    out = run(be.extract(["https://e.com/a", "https://e.com/bad"]))
    assert out[0].content == "body" and out[0].title == "A"
    assert out[1].error == "blocked" and out[1].url == "https://e.com/bad"


def test_extract_maps_backend_error_to_items(monkeypatch):
    be = _backend(lambda req: httpx.Response(429, text="slow"), _cfg(monkeypatch))
    out = run(be.extract(["https://e.com/a", "https://e.com/b"]))
    assert [item.url for item in out] == ["https://e.com/a", "https://e.com/b"]
    assert all(item.error for item in out)


def test_search_maps_errors(monkeypatch):
    def handler(req):
        return httpx.Response(429, text="slow")

    be = _backend(handler, _cfg(monkeypatch))
    try:
        run(be.search("q"))
    except base.BackendError as exc:
        assert exc.reason == "rate_limited"
    else:
        raise AssertionError("expected BackendError")


def test_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    be = _backend(lambda req: httpx.Response(200, json={}), load_config())
    try:
        run(be.search("q"))
    except base.BackendError as exc:
        assert exc.reason == "unavailable"
    else:
        raise AssertionError("expected unavailable")
