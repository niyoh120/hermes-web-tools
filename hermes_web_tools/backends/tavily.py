"""Tavily backend — /search and /extract, with sticky multi-key rotation.

Auth: ``api_key`` in the JSON body (widely supported across Tavily API versions).

Key rotation (sticky):
- default to the current key
- HTTP 429 -> advance to next key, retry within the same call
- HTTP 401/403 -> drop the key from the pool, continue
- exhaust the pool -> raise BackendError(rate_limited|auth)

All pool mutations are guarded by an ``asyncio.Lock`` so concurrent requests
don't race the index.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import Config
from .base import BackendError, ExtractItem, SearchItem, request_json


class TavilyBackend:
    name = "tavily"

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client
        self._keys: list[str] = list(cfg.tavily_keys)
        self._idx = 0
        self._lock = asyncio.Lock()

    def available(self) -> bool:
        return bool(self._keys)

    async def _next_key(self, tried: set[str], drop: str | None = None) -> str | None:
        """Return the current sticky key, skipping keys tried by this request."""
        async with self._lock:
            if drop is not None and drop in self._keys:
                self._keys.remove(drop)
                if self._idx >= len(self._keys):
                    self._idx = 0
            if not self._keys:
                return None
            n = len(self._keys)
            for step in range(n):
                idx = (self._idx + step) % n
                key = self._keys[idx]
                if key not in tried:
                    self._idx = idx
                    return key
            return None

    async def _advance_after(self, key: str) -> None:
        async with self._lock:
            if key in self._keys and len(self._keys) > 1:
                self._idx = (self._keys.index(key) + 1) % len(self._keys)

    async def _request(self, path: str, body: dict, timeout: float) -> Any:
        """Try each key at most once for this request, rotating on 429/auth."""
        tried: set[str] = set()
        last_error: BackendError | None = None
        drop: str | None = None
        while True:
            key = await self._next_key(tried, drop=drop)
            if key is None:
                break
            drop = None
            payload = {**body, "api_key": key}
            client = self._client or httpx.AsyncClient()
            try:
                return await request_json(
                    client,
                    "POST",
                    f"{self.cfg.tavily_base_url}{path}",
                    json_body=payload,
                    timeout=timeout,
                )
            except BackendError as exc:
                last_error = exc
                tried.add(key)
                if exc.reason == "auth":
                    drop = key
                    continue
                if exc.reason == "rate_limited":
                    await self._advance_after(key)
                    await asyncio.sleep(0)  # yield before trying next key; no test slowdown
                    continue
                raise
            finally:
                if self._client is None:
                    await client.aclose()
        reason = last_error.reason if last_error else "unavailable"
        raise BackendError(reason, f"all tavily keys exhausted ({reason})")

    # --- search ---

    async def search(
        self, query: str, limit: int = 5, search_depth: str = "basic"
    ) -> list[SearchItem]:
        body: dict[str, Any] = {
            "query": query,
            "max_results": limit,
            "search_depth": search_depth,
            "include_answer": False,
        }
        data = await self._request("/search", body, self.cfg.search_timeout)
        items: list[SearchItem] = []
        for idx, r in enumerate(data.get("results", []) or []):
            items.append(
                SearchItem(
                    title=r.get("title", "") or "",
                    url=r.get("url", "") or "",
                    description=r.get("content", "") or "",
                    provider=self.name,
                    position=idx + 1,
                    extra={"score": r.get("score")},
                )
            )
        return items

    # --- extract ---

    async def extract(self, urls: list[str]) -> list[ExtractItem]:
        try:
            data = await self._request("/extract", {"urls": urls}, self.cfg.extract_timeout)
        except BackendError as exc:
            return [
                ExtractItem(url=url, error=str(exc) or exc.reason, metadata={"provider": self.name})
                for url in urls
            ]
        out: list[ExtractItem] = []
        for r in data.get("results", []) or []:
            out.append(
                ExtractItem(
                    url=r.get("url", "") or "",
                    title=r.get("title", "") or "",
                    content=r.get("content", "") or r.get("raw_content", "") or "",
                    raw_content=r.get("raw_content", "") or "",
                    metadata={"provider": self.name},
                )
            )
        for r in data.get("failed_results", []) or []:
            out.append(
                ExtractItem(
                    url=r.get("url", "") or "",
                    error=r.get("error", "tavily extract failed") or "tavily extract failed",
                    metadata={"provider": self.name},
                )
            )
        return out
