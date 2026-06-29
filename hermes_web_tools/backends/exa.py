"""Exa backend — /search, /contents (extract), /context (code), /answer (Q&A).

Endpoints (https://api.exa.ai):
- POST /search        -> list of webpages (+ optional contents)
- POST /contents      -> extract by known URL ids
- POST /context       -> code-context text (Exa Code)
- POST /answer        -> grounded answer with citations

Auth: ``x-api-key`` header. We call HTTP directly (no exa-py dependency) so
the plugin loads even when the SDK is absent.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Config
from .base import BackendError, ExtractItem, SearchItem, request_json


class ExaBackend:
    name = "exa"

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client

    def _headers(self) -> dict[str, str]:
        if not self.cfg.exa_api_key:
            raise BackendError("unavailable", "EXA_API_KEY not set")
        return {"x-api-key": self.cfg.exa_api_key}

    async def _post(self, path: str, body: dict, timeout: float | None = None) -> Any:
        client = self._client or httpx.AsyncClient()
        try:
            return await request_json(
                client,
                "POST",
                f"{self.cfg.exa_base_url}{path}",
                headers=self._headers(),
                json_body=body,
                timeout=timeout or self.cfg.search_timeout,
            )
        finally:
            if self._client is None:
                await client.aclose()

    # --- search ---

    async def search(
        self,
        query: str,
        limit: int = 5,
        category: str | None = None,
        search_type: str = "auto",
        include_text: bool = False,
    ) -> list[SearchItem]:
        body: dict[str, Any] = {
            "query": query,
            "type": search_type,
            "numResults": limit,
            "contents": {"text": True} if include_text else {"highlights": True},
        }
        if category and category != "auto":
            body["category"] = category
        data = await self._post("/search", body)
        results = data.get("results", []) or []
        items: list[SearchItem] = []
        for idx, r in enumerate(results):
            text = r.get("text") if include_text else None
            highlights = r.get("highlights") or []
            desc = (highlights[0] if highlights else "") or r.get("summary", "") or ""
            items.append(
                SearchItem(
                    title=r.get("title", "") or "",
                    url=r.get("url", "") or "",
                    description=desc,
                    provider=self.name,
                    position=idx + 1,
                    extra={"published_date": r.get("publishedDate")},
                )
            )
            # ponytail: include_text path attaches full text to first item only
            # to keep token usage bounded; callers wanting full text use extract.
            if text and idx == 0:
                items[0].extra["text"] = text
        return items

    # --- code context (/context) ---

    async def context(self, query: str, max_tokens: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "tokensNum": max_tokens if max_tokens is not None else "dynamic",
        }
        data = await self._post("/context", body, timeout=self.cfg.search_timeout)
        return {
            "code_context": data.get("response", "") or "",
            "results_count": data.get("resultsCount", 0) or 0,
            "metadata": {
                "cost_dollars": data.get("costDollars"),
                "search_time": data.get("searchTime"),
                "output_tokens": data.get("outputTokens"),
            },
        }

    # --- answer (/answer) ---

    async def answer(self, query: str, text: bool = True) -> dict[str, Any]:
        data = await self._post(
            "/answer", {"query": query, "text": text}, timeout=self.cfg.extract_timeout
        )
        citations = []
        for c in data.get("citations", []) or []:
            citations.append(
                {
                    "title": c.get("title", "") or "",
                    "url": c.get("url", "") or "",
                    "content": c.get("text", "") or "",
                }
            )
        return {"answer": data.get("answer", "") or "", "citations": citations}

    # --- extract (/contents) ---

    async def extract(self, urls: list[str]) -> list[ExtractItem]:
        body: dict[str, Any] = {"ids": urls, "text": True}
        try:
            data = await self._post("/contents", body, timeout=self.cfg.extract_timeout)
        except BackendError as exc:
            return [
                ExtractItem(url=url, error=str(exc) or exc.reason, metadata={"provider": self.name})
                for url in urls
            ]
        out: list[ExtractItem] = []
        for r in data.get("results", []) or []:
            out.append(
                ExtractItem(
                    url=r.get("url", "") or r.get("id", "") or "",
                    title=r.get("title", "") or "",
                    content=r.get("text", "") or "",
                    raw_content=r.get("text", "") or "",
                    metadata={"provider": self.name},
                )
            )
        # Exa /contents returns statuses for failures (e.g. blocked URLs).
        statuses = data.get("statuses", []) or []
        for s in statuses:
            if s.get("success", True) is False:
                out.append(
                    ExtractItem(
                        url=s.get("id", "") or "",
                        error=s.get("error", "exa extract failed") or "exa extract failed",
                        metadata={"provider": self.name},
                    )
                )
        return out
