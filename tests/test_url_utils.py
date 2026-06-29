"""Tests for url_utils — normalize, SSRF, document detection."""

from __future__ import annotations

import socket

import pytest

from hermes_web_tools import url_utils

# ---------- normalize ----------


def test_normalize_lowercases_scheme_and_host_only():
    assert url_utils.normalize_url("HTTPS://Example.COM/Path?Q=1") == "https://example.com/Path?Q=1"


def test_normalize_preserves_www():
    assert url_utils.normalize_url("https://www.example.com/x") == "https://www.example.com/x"
    assert url_utils.normalize_url("https://example.com/x") == "https://example.com/x"


def test_normalize_strips_tracking_params():
    assert (
        url_utils.normalize_url("https://e.com/x?utm_source=a&keep=1&fbclid=z&id=2")
        == "https://e.com/x?keep=1&id=2"
    )


def test_normalize_preserves_query_case():
    assert url_utils.normalize_url("https://e.com/x?Key=Value") == "https://e.com/x?Key=Value"


def test_normalize_strips_trailing_slash_non_root():
    assert url_utils.normalize_url("https://e.com/x/") == "https://e.com/x"
    assert url_utils.normalize_url("https://e.com/") == "https://e.com/"


def test_normalize_drops_fragment():
    assert url_utils.normalize_url("https://e.com/x#a") == "https://e.com/x"


def test_normalize_same_result_for_dup():
    a = url_utils.normalize_url("https://e.com/x?utm_source=1&k=2")
    b = url_utils.normalize_url("https://e.com/x?k=2&utm_medium=3")
    assert a == b


# ---------- scheme ----------


def test_is_safe_scheme():
    assert url_utils.is_safe_scheme("http://x")
    assert url_utils.is_safe_scheme("https://x")
    assert not url_utils.is_safe_scheme("file:///etc/passwd")
    assert not url_utils.is_safe_scheme("ftp://x")


# ---------- document detection ----------


def test_is_document_url():
    assert url_utils.is_document_url("https://e.com/p.pdf")
    assert url_utils.is_document_url("https://e.com/x.DOCX")
    assert url_utils.is_document_url("https://e.com/a/b.xlsx")
    assert not url_utils.is_document_url("https://e.com/page.html")
    assert not url_utils.is_document_url("https://e.com/unknown")


def test_is_valid_http_url():
    assert url_utils.is_valid_http_url("https://example.com/x")
    assert url_utils.is_valid_http_url("http://e.com")
    assert not url_utils.is_valid_http_url("ftp://e.com")
    assert not url_utils.is_valid_http_url("not a url")
    assert not url_utils.is_valid_http_url("")


# ---------- SSRF ----------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",
        "[::1]",
        "[fc00::1]",
        "0.0.0.0",
    ],
)
def test_blocked_literal_ips(ip):
    assert not url_utils.is_safe_url(f"http://{ip}/x")


@pytest.mark.parametrize("port", ["22", "3306", "6379", "9000", "1"])
def test_blocked_ports(port):
    assert not url_utils.is_safe_url(f"https://example.com:{port}/x")


def test_allowed_public_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [])
    assert url_utils.is_safe_url("https://1.1.1.1/x")


def test_dns_resolving_to_private_is_blocked(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **kw):
        return [(None, None, None, None, ("192.168.1.50", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert not url_utils.is_safe_url("https://internal.example.com/x")


def test_dns_resolving_to_public_is_ok(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **kw):
        return [(None, None, None, None, ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert url_utils.is_safe_url("https://example.com/x")


def test_dns_failure_is_unsafe(monkeypatch):
    def boom(*a, **kw):
        raise OSError("dns fail")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert not url_utils.is_safe_url("https://nope.invalid/x")


def test_dns_timeout_is_unsafe(monkeypatch):
    import time

    monkeypatch.setattr(url_utils, "_DNS_TIMEOUT_SECONDS", 0.001)

    def slow(*a, **kw):
        time.sleep(0.05)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", slow)
    assert not url_utils.is_safe_url("https://slow.example.com/x")


def test_validate_url_raises():
    with pytest.raises(url_utils.UnsafeUrlError, match="URL scheme not allowed") as scheme_exc:
        url_utils.validate_url("file:///etc/passwd?token=secret")
    assert "secret" not in str(scheme_exc.value)
    with pytest.raises(url_utils.UnsafeUrlError, match="URL failed SSRF check") as ssrf_exc:
        url_utils.validate_url("http://127.0.0.1/x?token=secret")
    assert "secret" not in str(ssrf_exc.value)


def test_url_regex_extracts():
    text = "see https://e.com/a and http://b.com/x?q=1, ok"
    assert url_utils._URL_REGEX.findall(text) == ["https://e.com/a", "http://b.com/x?q=1,"]
