"""Tavily backend — /search and /extract.

Auth: ``api_key`` in the JSON body (widely supported across Tavily API versions).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Config
from .base import BackendError, ExtractItem, SearchItem, request_json


class TavilyBackend:
    name = "tavily"

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client

    def available(self) -> bool:
        return bool(self.cfg.tavily_api_key)

    async def _request(self, path: str, body: dict, timeout: float) -> Any:
        if not self.available():
            raise BackendError("unavailable", "TAVILY_API_KEY not set")
        payload = {**body, "api_key": self.cfg.tavily_api_key}
        client = self._client or httpx.AsyncClient()
        try:
            return await request_json(
                client,
                "POST",
                f"{self.cfg.tavily_base_url}{path}",
                json_body=payload,
                timeout=timeout,
            )
        finally:
            if self._client is None:
                await client.aclose()

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
