"""URL utilities — conservative normalize, SSRF guard, document-type detection.

Conservative normalize (per plan):
- lowercase only scheme + host
- do NOT touch www
- do NOT lowercase path/query (case-sensitive on many services)
- strip known tracking query params (utm_*, fbclid, gclid, ref, src)
- drop trailing slash only when path is non-root

SSRF guard:
- scheme must be http or https
- host resolves to non-loopback / non-private / non-link-local / non-reserved
- port must be in the allowed set (default 80, 443, 8000, 8001, 8080,
  8443, 8888; callers can pass a wider set)
- redirect targets must be re-validated by the caller (we expose is_safe_url
  for that)

Document-type detection:
- by URL path suffix first (pdf/doc(x)/ppt(x)/xls(x)/images)
- HEAD Content-Type fallback is handled by the extract router, not here.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import re
import socket
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Known tracking params. utm_* matched by prefix.
_TRACKING_EXACT: set[str] = {"fbclid", "gclid", "ref", "src"}
_TRACKING_PREFIXES = ("utm_",)

_DOC_SUFFIXES = (
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
)

_ALLOWED_SCHEMES = ("http", "https")
# Default allowed ports. Covers common public HTTP(S) and dev HTTP(S) ports;
# callers can pass a stricter set.
_DEFAULT_ALLOWED_PORTS: set[int] = {80, 443, 8000, 8001, 8080, 8443, 8888}
_DNS_TIMEOUT_SECONDS = 5.0


class UnsafeUrlError(ValueError):
    """Raised when a URL fails SSRF / scheme validation."""


def _strip_tracking(params: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    kept: list[tuple[str, str]] = []
    for k, v in params:
        kl = k.lower()
        if kl in _TRACKING_EXACT:
            continue
        if any(kl.startswith(p) for p in _TRACKING_PREFIXES):
            continue
        kept.append((k, v))
    return kept


def normalize_url(url: str) -> str:
    """Return a canonical key for dedup. Conservative — see module docstring."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # Path: keep case, strip one trailing slash unless root.
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # Query: keep order and case, drop tracking params.
    query = urlencode(_strip_tracking(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))  # drop fragment


def is_safe_scheme(url: str) -> bool:
    return urlsplit(url).scheme.lower() in _ALLOWED_SCHEMES


def _host_is_blocked_ip(host: str) -> bool:
    """True if host is a literal IP we must refuse."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # hostname, resolve separately
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolved_ips(host: str, port: int) -> list[str]:
    # socket.getaddrinfo has no per-call timeout; use a private worker so a
    # slow resolver cannot exhaust asyncio's default thread pool.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    try:
        infos = future.result(timeout=_DNS_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise OSError("DNS lookup timeout") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return list({info[4][0] for info in infos})


def is_safe_url(url: str, allowed_ports: set[int] | None = None) -> bool:
    """Full SSRF check. Resolves DNS and rejects blocked IPs.

    Makes a network call (DNS) — callers must only invoke this after deciding
    to touch the URL, and should re-check redirect targets with it.
    """
    if not is_safe_scheme(url):
        return False
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        return False
    port = None
    try:
        port = parts.port
    except ValueError:
        return False  # malformed port / bare IPv6 without brackets
    ports = allowed_ports or _DEFAULT_ALLOWED_PORTS
    if port is None:
        port = 443 if parts.scheme.lower() == "https" else 80
    if port not in ports:
        return False
    # Literal IP host.
    if _host_is_blocked_ip(host):
        return False
    # Hostname -> resolve every A/AAAA and refuse any blocked IP.
    try:
        ips = _resolved_ips(host, port or 443)
    except OSError:
        return False
    for ip_str in ips:
        if _host_is_blocked_ip(ip_str):
            return False
    return True


def validate_url(url: str, allowed_ports: set[int] | None = None) -> None:
    """Raise UnsafeUrlError unless the URL is scheme-valid AND SSRF-safe."""
    if not is_safe_scheme(url):
        raise UnsafeUrlError("URL scheme not allowed (http/https only)")
    if not is_safe_url(url, allowed_ports=allowed_ports):
        raise UnsafeUrlError("URL failed SSRF check")


def is_document_url(url: str) -> bool:
    """Heuristic by path suffix. HEAD Content-Type fallback lives in router."""
    path = urlsplit(url).path.lower()
    return path.endswith(_DOC_SUFFIXES)


def is_valid_http_url(url: str) -> bool:
    """Cheap structural check for Grok-returned URLs (no DNS)."""
    if not isinstance(url, str) or not url.strip():
        return False
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    return bool(parts.netloc)


# Regex for extracting URLs from free-form text. Grok backend currently uses JSON parsing.
_URL_REGEX = re.compile(r"https?://[^\s\"'<>]+")
_TRAILING_JUNK_RE = re.compile(r"[,.;:)!}\]>]+$")


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text and strip common trailing punctuation."""
    return [_TRAILING_JUNK_RE.sub("", u) for u in _URL_REGEX.findall(text)]
