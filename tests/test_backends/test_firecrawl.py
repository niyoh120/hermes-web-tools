"""Tests for Firecrawl backend — per-URL scrape + isolated failures."""

from __future__ import annotations

import asyncio

import httpx

from hermes_web_tools.backends.firecrawl import FirecrawlBackend
from hermes_web_tools.config import Config


def run(coro):
    return asyncio.run(coro)


def _cfg(key="fc-key"):
    cfg = Config()
    cfg.firecrawl_api_key = key
    cfg.extract_timeout = 10
    return cfg


def _backend(handler, cfg):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return FirecrawlBackend(cfg, client=client)


def test_extract_success(monkeypatch):
    seen = {}

    def handler(req):
        seen["path"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        # echo which URL is being scraped
        import json as _j

        body = _j.loads(req.content)
        url = body["url"]
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"markdown": f"# {url}", "metadata": {"title": "T", "sourceURL": url}},
            },
        )

    cfg = _cfg()
    cfg.firecrawl_base_url = "https://fire.local"
    out = run(_backend(handler, cfg).extract(["https://a.com", "https://b.com"]))
    assert seen["path"] == "https://fire.local/v1/scrape"
    assert seen["auth"] == "Bearer fc-key"
    assert len(out) == 2
    assert out[0].url == "https://a.com" and out[0].title == "T"
    assert out[0].content.startswith("# https://a.com")
    assert out[0].metadata["provider"] == "firecrawl"


def test_extract_isolates_per_url_failure():
    def handler(req):
        import json as _j

        url = _j.loads(req.content)["url"]
        if url == "https://bad.com":
            return httpx.Response(429, text="slow")
        return httpx.Response(
            200, json={"data": {"markdown": "ok", "metadata": {"sourceURL": url}}}
        )

    out = run(_backend(handler, _cfg()).extract(["https://a.com", "https://bad.com"]))
    urls = {o.url: o for o in out}
    assert urls["https://a.com"].content == "ok"
    assert urls["https://bad.com"].error  # non-empty
    assert urls["https://bad.com"].metadata["provider"] == "firecrawl"


def test_extract_converts_cancelled_error():
    be = _backend(lambda req: httpx.Response(200), _cfg())

    async def cancelled(url):
        raise asyncio.CancelledError("bye")

    be._scrape_one = cancelled  # type: ignore[method-assign]
    out = run(be.extract(["https://a.com"]))
    assert out[0].url == "https://a.com"
    assert out[0].metadata["provider"] == "firecrawl"
    assert out[0].error


def test_unavailable_without_key():
    be = _backend(lambda req: httpx.Response(200), _cfg(key=""))
    assert be.available() is False
    # extract without a key surfaces per-URL errors (router skips via available()).
    out = run(be.extract(["https://a.com"]))
    assert out and out[0].error
