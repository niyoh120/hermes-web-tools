"""Tests for Tavily backend — search/extract + sticky multi-key rotation."""

from __future__ import annotations

import asyncio

import httpx

from hermes_web_tools.backends import base
from hermes_web_tools.backends.tavily import TavilyBackend
from hermes_web_tools.config import Config


def run(coro):
    return asyncio.run(coro)


def _cfg(keys=("k1", "k2", "k3")):
    cfg = Config()
    cfg.tavily_keys = list(keys)
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
    assert b'"max_results":3' in seen["body"]


def test_search_depth_advanced():
    seen = {}

    def handler(req):
        seen["body"] = req.content
        return httpx.Response(200, json={"results": []})

    run(_backend(handler, _cfg()).search("q", search_depth="advanced"))
    assert b'"search_depth":"advanced"' in seen["body"]


def test_429_rotates_to_next_key():
    calls = []

    def handler(req):
        body = req.content.decode()
        for k in ("k1", "k2", "k3"):
            if f'"api_key":"{k}"' in body:
                calls.append(k)
                if k == "k3":
                    return httpx.Response(
                        200, json={"results": [{"title": "ok", "url": "https://t/a"}]}
                    )
                return httpx.Response(429, text="slow")
        return httpx.Response(401)

    items = run(_backend(handler, _cfg()).search("q"))
    assert calls == ["k1", "k2", "k3"]
    assert items[0].title == "ok"


def test_401_drops_key_and_continues():
    calls = []

    def handler(req):
        body = req.content.decode()
        for k in ("k1", "k2"):
            if f'"api_key":"{k}"' in body:
                calls.append(k)
                if k == "k1":
                    return httpx.Response(401, text="bad key")
                return httpx.Response(200, json={"results": []})
        return httpx.Response(500)

    be = _backend(handler, _cfg(keys=("k1", "k2")))
    run(be.search("q"))
    assert calls == ["k1", "k2"]
    assert be._keys == ["k2"]  # k1 dropped


def test_all_keys_429_raises_rate_limited():
    def handler(req):
        return httpx.Response(429, text="slow")

    try:
        run(_backend(handler, _cfg()).search("q"))
    except base.BackendError as exc:
        assert exc.reason == "rate_limited"
    else:
        raise AssertionError("expected rate_limited")


def test_no_keys_raises_unavailable():
    be = _backend(lambda req: httpx.Response(200), _cfg(keys=()))
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


def test_concurrent_rotation_no_race():
    """Two concurrent searches both hit 429 on k1; both must advance safely."""
    import threading

    state = {"k1_hits": 0, "lock": threading.Lock()}

    def handler(req):
        body = req.content.decode()
        if '"api_key":"k1"' in body:
            with state["lock"]:
                state["k1_hits"] += 1
            return httpx.Response(429, text="slow")
        if '"api_key":"k2"' in body:
            return httpx.Response(200, json={"results": []})
        return httpx.Response(401)

    be = _backend(handler, _cfg(keys=("k1", "k2")))

    async def go():
        return await asyncio.gather(be.search("q"), be.search("q"))

    run(go())
    # k1 hit at least once; no exception raised means rotation was safe.
    assert state["k1_hits"] >= 1
