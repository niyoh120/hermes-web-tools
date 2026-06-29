"""Tests for backends/base — error mapping and request_json via MockTransport."""

from __future__ import annotations

import httpx
import pytest

from hermes_web_tools.backends import base


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_map_http_error_categories():
    assert base.map_http_error(httpx.Response(401)).reason == "auth"
    assert base.map_http_error(httpx.Response(403)).reason == "auth"
    assert base.map_http_error(httpx.Response(429)).reason == "rate_limited"
    assert base.map_http_error(httpx.Response(500)).reason == "http"
    assert base.map_http_error(httpx.Response(404)).reason == "not_found"
    assert base.map_http_error(httpx.Response(400)).reason == "bad_request"
    assert base.map_http_error(httpx.Response(402)).reason == "billing"


def run(coro):
    import asyncio

    return asyncio.run(coro)


def test_request_json_success():
    def handler(req):
        return httpx.Response(200, json={"ok": True})

    data = run(base.request_json(_client(handler), "POST", "https://x/api"))
    assert data == {"ok": True}


def test_request_json_http_error():
    def handler(req):
        return httpx.Response(429, text="slow down")

    with pytest.raises(base.BackendError) as ei:
        run(base.request_json(_client(handler), "POST", "https://x/api"))
    assert ei.value.reason == "rate_limited"
    assert ei.value.status_code == 429


def test_request_json_timeout():
    def handler(req):
        raise httpx.TimeoutException("timed out")

    with pytest.raises(base.BackendError) as ei:
        run(base.request_json(_client(handler), "POST", "https://x/api", timeout=1.0))
    assert ei.value.reason == "timeout"


def test_request_json_network():
    def handler(req):
        raise httpx.ConnectError("nope")

    with pytest.raises(base.BackendError) as ei:
        run(base.request_json(_client(handler), "POST", "https://x/api"))
    assert ei.value.reason == "network"


def test_request_json_non_json():
    def handler(req):
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(base.BackendError) as ei:
        run(base.request_json(_client(handler), "POST", "https://x/api"))
    assert ei.value.reason == "parse"
