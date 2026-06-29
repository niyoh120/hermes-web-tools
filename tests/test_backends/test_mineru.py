"""Tests for MinerU backend — submit/poll/zip and agent fallback."""

from __future__ import annotations

import asyncio
import io
import zipfile

import httpx

from hermes_web_tools.backends.mineru import MinerUBackend
from hermes_web_tools.config import Config


def run(coro):
    return asyncio.run(coro)


def _zip_bytes(name="full.md", content="# parsed"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


def _cfg(token="tok", fallback=False):
    cfg = Config()
    cfg.mineru_api_token = token
    cfg.mineru_agent_fallback_enabled = fallback
    cfg.mineru_model_version = "vlm"
    cfg.search_timeout = 5
    cfg.extract_timeout = 1
    return cfg


def _backend(handler, cfg):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MinerUBackend(cfg, client=client)


def test_precision_success_downloads_full_md(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: True)
    calls = []

    def handler(req):
        calls.append((req.method, str(req.url)))
        if req.method == "POST" and str(req.url).endswith("/api/v4/extract/task"):
            assert req.headers.get("authorization") == "Bearer tok"
            assert b'"model_version":"vlm"' in req.content
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "t1"}})
        if req.method == "GET" and str(req.url).endswith("/api/v4/extract/task/t1"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"state": "done", "full_zip_url": "https://cdn/z.zip"}},
            )
        if req.method == "GET" and str(req.url) == "https://cdn/z.zip":
            return httpx.Response(200, content=_zip_bytes(content="# hello"))
        return httpx.Response(404)

    cfg = _cfg()
    cfg.mineru_base_url = "https://mineru.local"
    out = run(_backend(handler, cfg).extract(["https://e.com/a.pdf"]))
    assert calls[0][1] == "https://mineru.local/api/v4/extract/task"
    assert out[0].content == "# hello"
    assert out[0].metadata["provider"] == "mineru"
    assert calls[0][0] == "POST"


def test_precision_rejects_unsafe_download_url(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: False)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        if str(req.url).endswith("/t1"):
            return httpx.Response(
                200, json={"data": {"state": "done", "full_zip_url": "https://cdn/z.zip"}}
            )
        return httpx.Response(200, content=_zip_bytes())

    out = run(_backend(handler, _cfg()).extract(["https://e.com/a.pdf"]))
    assert "unsafe" in out[0].error.lower()


def test_html_uses_html_model(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: True)
    seen = {}

    def handler(req):
        if req.method == "POST":
            seen["body"] = req.content
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        if str(req.url).endswith("/t1"):
            return httpx.Response(
                200, json={"data": {"state": "done", "full_zip_url": "https://cdn/z.zip"}}
            )
        return httpx.Response(200, content=_zip_bytes())

    run(_backend(handler, _cfg()).extract(["https://e.com/a.html?x=1"]))
    assert b'"model_version":"MinerU-HTML"' in seen["body"]


def test_precision_failed_state_returns_error():
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        return httpx.Response(200, json={"data": {"state": "failed", "err_msg": "parse bad"}})

    out = run(_backend(handler, _cfg()).extract(["https://e.com/a.pdf"]))
    assert out[0].error == "parse bad"


def test_precision_timeout_returns_error(monkeypatch):
    import hermes_web_tools.backends.mineru as mineru_mod

    monkeypatch.setattr(mineru_mod, "_POLL_INTERVAL", 0.0)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        return httpx.Response(200, json={"data": {"state": "running"}})

    cfg = _cfg()
    cfg.extract_timeout = 0
    out = run(_backend(handler, cfg).extract(["https://e.com/a.pdf"]))
    assert "timeout" in out[0].error


def test_agent_fallback_inline_markdown_url(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: True)

    def handler(req):
        if req.method == "POST" and str(req.url).endswith("/api/v1/agent/parse/url"):
            return httpx.Response(200, json={"data": {"markdown_url": "https://cdn/full.md"}})
        if str(req.url) == "https://cdn/full.md":
            return httpx.Response(200, text="# agent")
        return httpx.Response(404)

    out = run(_backend(handler, _cfg(token="", fallback=True)).extract(["https://e.com/a.pdf"]))
    assert out[0].content == "# agent"


def test_unavailable_without_token_or_fallback():
    be = _backend(lambda req: httpx.Response(500), _cfg(token="", fallback=False))
    assert be.available() is False
    out = run(be.extract(["https://e.com/a.pdf"]))
    assert out[0].error == "mineru unavailable"


def test_zip_markdown_size_limit(monkeypatch):
    import hermes_web_tools.backends.mineru as mineru_mod

    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: True)
    monkeypatch.setattr(mineru_mod, "_MAX_DECOMPRESSED_BYTES", 3)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        if str(req.url).endswith("/t1"):
            return httpx.Response(
                200, json={"data": {"state": "done", "full_zip_url": "https://cdn/z.zip"}}
            )
        return httpx.Response(200, content=_zip_bytes(content="1234"))

    out = run(_backend(handler, _cfg()).extract(["https://e.com/a.pdf"]))
    assert "too large" in out[0].error


def test_download_redirect_returns_clear_error(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: True)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        if str(req.url).endswith("/t1"):
            return httpx.Response(
                200, json={"data": {"state": "done", "full_zip_url": "https://cdn/z.zip"}}
            )
        return httpx.Response(302, headers={"location": "https://cdn/next.zip"})

    out = run(_backend(handler, _cfg()).extract(["https://e.com/a.pdf"]))
    assert "redirect" in out[0].error


def test_per_url_exception_isolation(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: True)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        return httpx.Response(200, json=[1, 2, 3])

    out = run(_backend(handler, _cfg()).extract(["https://e.com/a.pdf"]))
    assert out[0].error


def test_zip_without_markdown_returns_error(monkeypatch):
    monkeypatch.setattr("hermes_web_tools.backends.mineru.is_safe_url", lambda url: True)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        if str(req.url).endswith("/t1"):
            return httpx.Response(
                200, json={"data": {"state": "done", "full_zip_url": "https://cdn/z.zip"}}
            )
        return httpx.Response(200, content=_zip_bytes(name="x.txt", content="no md"))

    out = run(_backend(handler, _cfg()).extract(["https://e.com/a.pdf"]))
    assert "no markdown" in out[0].error
