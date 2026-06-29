"""Tests for Tavily backend — search/extract via single API key."""

from __future__ import annotations

import asyncio

import httpx

from hermes_web_tools.backends import base
from hermes_web_tools.backends.tavily import TavilyBackend
from hermes_web_tools.config import Config


def run(coro):
    return asyncio.run(coro)


def _cfg(key="k1"):
    cfg = Config()
    cfg.tavily_api_key = key
    cfg.search_timeout = 5
    cfg.extract_timeout = 10
    return cfg


def _backend(handler, cfg):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TavilyBackend(cfg, client=client)


def test_search_normalizes(monkeypatch):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = req.content
        return httpx.Response(
            200, json={"results": [{"title": "T", "url": "https://t/a", "content": "c"}]}
        )

    cfg = _cfg()
    cfg.tavily_base_url = "https://tavily.local"
    be = _backend(handler, cfg)
    items = run(be.search("q", limit=3))
    assert seen["url"] == "https://tavily.local/search"
    assert items[0].title == "T" and items[0].provider == "tavily" and items[0].position == 1
    assert b'"api_key":"k1"' in seen["body"]
    assert b'"max_results":3' in seen["body"]


def test_search_depth_advanced():
    seen = {}

    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"results": []})

    run(_backend(handler, _cfg()).search("q", search_depth="advanced"))
    assert b'"search_depth":"advanced"' in seen["body"]


def test_429_raises_rate_limited():
    def handler(req):
        return httpx.Response(429, text="slow")

    try:
        run(_backend(handler, _cfg()).search("q"))
    except base.BackendError as exc:
        assert exc.reason == "rate_limited"
    else:
        raise AssertionError("expected rate_limited")


def test_no_key_raises_unavailable():
    be = _backend(lambda req: httpx.Response(200), _cfg(key=""))
    assert be.available() is False
    try:
        run(be.search("q"))
    except base.BackendError as exc:
        assert exc.reason == "unavailable"
    else:
        raise AssertionError("expected unavailable")


def test_extract_normalizes_and_failed():
    def handler(req):
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://t/a", "raw_content": "body"}],
                "failed_results": [{"url": "https://t/bad", "error": "boom"}],
            },
        )

    out = run(_backend(handler, _cfg()).extract(["https://t/a", "https://t/bad"]))
    assert out[0].content == "body" and out[0].raw_content == "body"
    assert out[1].error == "boom" and out[1].url == "https://t/bad"


def test_extract_backend_error_returns_per_url_errors():
    def handler(req):
        return httpx.Response(401, text="bad key")

    out = run(_backend(handler, _cfg()).extract(["https://t/a", "https://t/b"]))
    assert [item.url for item in out] == ["https://t/a", "https://t/b"]
    assert all(item.error for item in out)
