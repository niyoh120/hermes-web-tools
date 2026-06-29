"""Firecrawl backend — extract via the synchronous ``/v1/scrape`` endpoint.

We scrape each URL in parallel (HTTP-level gather) rather than the async batch
job, so there's no polling and per-URL failures are isolated. This fits our
``max_urls <= 10`` envelope; for thousands of URLs the batch API would be
better, but that's out of scope.

Auth: ``Authorization: Bearer <key>``. Response: ``{success, data:{markdown,
metadata:{title, sourceURL, description}}}``.
"""

from __future__ import annotations

import asyncio

import httpx

from ..config import Config
from .base import BackendError, ExtractItem, request_json


class FirecrawlBackend:
    name = "firecrawl"

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client

    def available(self) -> bool:
        return bool(self.cfg.firecrawl_api_key)

    async def _scrape_one(self, url: str) -> ExtractItem:
        if not self.available():
            raise BackendError("unavailable", "FIRECRAWL_API_KEY not set")
        headers = {"Authorization": f"Bearer {self.cfg.firecrawl_api_key}"}
        body = {"url": url, "formats": ["markdown"]}
        client = self._client or httpx.AsyncClient()
        try:
            data = await request_json(
                client,
                "POST",
                f"{self.cfg.firecrawl_base_url}/v1/scrape",
                headers=headers,
                json_body=body,
                timeout=self.cfg.extract_timeout,
            )
        finally:
            if self._client is None:
                await client.aclose()
        if data.get("success") is False:
            raise BackendError("http", data.get("error", "firecrawl scrape failed"))
        d = data.get("data", {}) or {}
        meta = d.get("metadata", {}) or {}
        return ExtractItem(
            url=meta.get("sourceURL", url) or url,
            title=meta.get("title", "") or "",
            content=d.get("markdown", "") or "",
            raw_content=d.get("markdown", "") or "",
            metadata={"provider": self.name, "description": meta.get("description", "")},
        )

    async def extract(self, urls: list[str]) -> list[ExtractItem]:
        """Scrape all URLs in parallel. Per-URL failure -> ExtractItem.error."""
        # ponytail: per-URL client ephemeral; with injected shared client it's reused.
        tasks = [self._scrape_one(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[ExtractItem] = []
        for url, res in zip(urls, results):
            if isinstance(res, BackendError):
                out.append(
                    ExtractItem(
                        url=url, error=str(res) or res.reason, metadata={"provider": self.name}
                    )
                )
            elif isinstance(res, BaseException):
                out.append(
                    ExtractItem(
                        url=url,
                        error=str(res) or type(res).__name__,
                        metadata={"provider": self.name},
                    )
                )
            else:
                out.append(res)
        return out
