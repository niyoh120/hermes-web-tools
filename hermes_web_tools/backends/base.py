"""Backend base — shared types, error mapping, and an async HTTP helper.

Backends are thin: read config, send a request, normalize the response, map
runtime errors to ``BackendError``. The router catches ``BackendError`` and
skips that provider — no extra fallback chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


class BackendError(Exception):
    """A backend call failed. ``reason`` is one of: timeout / rate_limited /
    auth / http / network / parse / unavailable. ``status_code`` when relevant."""

    def __init__(self, reason: str, message: str = "", status_code: int | None = None):
        self.reason = reason
        self.status_code = status_code
        super().__init__(message or reason)


# Normalized search result — produced by every search backend. The router
# merges a list of these; merge.py stamps `source_count` / final `position`.
@dataclass
class SearchItem:
    title: str
    url: str
    description: str = ""
    provider: str = ""  # "exa" | "tavily" | "grok"
    position: int = 0  # within-provider position (1-based)
    extra: dict = field(default_factory=dict)  # provider-specific bits -> metadata


# Normalized extract result — one per URL.
@dataclass
class ExtractItem:
    url: str
    title: str = ""
    content: str = ""
    raw_content: str = ""
    metadata: dict = field(default_factory=dict)
    error: str = ""  # per-URL failure; empty on success


def map_http_error(resp: httpx.Response) -> BackendError:
    """Map an HTTP error status to a typed BackendError."""
    status = resp.status_code
    if status in (401, 403):
        return BackendError("auth", f"auth failed (HTTP {status})", status)
    if status == 429:
        return BackendError("rate_limited", "rate limited (HTTP 429)", status)
    if status == 402:
        return BackendError("billing", "payment required (HTTP 402)", status)
    if status == 404:
        return BackendError("not_found", "not found (HTTP 404)", status)
    if 400 <= status < 500:
        return BackendError("bad_request", f"client error (HTTP {status})", status)
    if 500 <= status < 600:
        return BackendError("http", f"server error (HTTP {status})", status)
    return BackendError("http", f"HTTP {status}", status)


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 15.0,
    follow_redirects: bool = False,
) -> Any:
    """Send a request, raise BackendError on failure, return parsed JSON.

    ``client`` is provided by the backend (real or injected for tests).
    """
    try:
        resp = await client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )
    except httpx.TimeoutException as exc:
        raise BackendError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise BackendError("network", str(exc)) from exc
    if 300 <= resp.status_code < 400:
        location = resp.headers.get("location", "unknown")[:200]
        raise BackendError("http", f"unexpected redirect (HTTP {resp.status_code} to {location})")
    if resp.status_code >= 400:
        raise map_http_error(resp)
    try:
        return resp.json()
    except ValueError as exc:
        raise BackendError("parse", f"non-JSON response: {exc}") from exc
