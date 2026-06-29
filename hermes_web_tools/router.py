"""Tool router — provider orchestration and envelope building.

Search tools:
- run their configured providers in parallel
- skip provider failures
- merge/dedup successful provider lists
- no extra fallback when results are sparse

Extract keeps an internal degradation chain for the same URL (doc: MinerU ->
Firecrawl -> Tavily; web: Firecrawl -> Tavily). That is a single extraction
operation, not search fallback.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any, Callable

from .backends.base import ExtractItem, SearchItem
from .backends.exa import ExaBackend
from .backends.firecrawl import FirecrawlBackend
from .backends.grok import GrokBackend
from .backends.mineru import MinerUBackend
from .backends.tavily import TavilyBackend
from .config import Config, load_config
from .merge import merge_search_results
from .url_utils import UnsafeUrlError, is_document_url, validate_url

SearchCall = Callable[[], Awaitable[list[SearchItem]]]


class ToolRouter:
    def __init__(
        self,
        cfg: Config | None = None,
        *,
        exa: ExaBackend | None = None,
        tavily: TavilyBackend | None = None,
        grok: GrokBackend | None = None,
        firecrawl: FirecrawlBackend | None = None,
        mineru: MinerUBackend | None = None,
    ):
        self.cfg = cfg or load_config()
        self.exa = exa or ExaBackend(self.cfg)
        self.tavily = tavily or TavilyBackend(self.cfg)
        self.grok = grok or GrokBackend(self.cfg)
        self.firecrawl = firecrawl or FirecrawlBackend(self.cfg)
        self.mineru = mineru or MinerUBackend(self.cfg)

    # ---------- search envelopes ----------

    async def web_search(self, query: str, limit: int = 5) -> dict:
        calls: list[tuple[str, SearchCall]] = []
        if self.cfg.has_tavily:
            calls.append(("tavily", lambda: self.tavily.search(query, limit=limit)))
        if self.cfg.has_exa:
            calls.append(("exa", lambda: self.exa.search(query, limit=limit)))
        return await self._run_search(calls, limit)

    async def web_search_realtime(self, query: str, limit: int = 5) -> dict:
        calls: list[tuple[str, SearchCall]] = []
        if self.cfg.has_grok:
            calls.append(("grok", lambda: self.grok.search(query, limit=limit)))
        if self.cfg.has_exa:
            calls.append(("exa", lambda: self.exa.search(query, limit=limit, category="news")))
        return await self._run_search(calls, limit)

    async def web_search_research(self, query: str, limit: int = 5) -> dict:
        calls: list[tuple[str, SearchCall]] = []
        if self.cfg.has_exa:
            calls.append(
                (
                    "exa",
                    lambda: self.exa.search(
                        query, limit=limit, category="research paper", search_type="deep"
                    ),
                )
            )
        if self.cfg.has_tavily:
            calls.append(
                ("tavily", lambda: self.tavily.search(query, limit=limit, search_depth="advanced"))
            )
        return await self._run_search(calls, limit)

    async def web_search_entities(
        self, query: str, limit: int = 5, entity_type: str = "auto"
    ) -> dict:
        category = _entity_category(entity_type)
        calls: list[tuple[str, SearchCall]] = []
        if self.cfg.has_exa:
            calls.append(("exa", lambda: self.exa.search(query, limit=limit, category=category)))
        if self.cfg.has_tavily:
            calls.append(("tavily", lambda: self.tavily.search(query, limit=limit)))
        return await self._run_search(calls, limit)

    async def web_search_code(self, query: str, max_tokens: int | None = None) -> dict:
        if not self.cfg.has_exa:
            return _failure("EXA_API_KEY not set")
        try:
            return {"success": True, "data": await self.exa.context(query, max_tokens=max_tokens)}
        except Exception as exc:  # noqa: BLE001 - tool envelope must never raise
            return _failure(str(exc))

    async def web_answer(self, query: str, text: bool = True) -> dict:
        if not self.cfg.has_exa:
            return _failure("EXA_API_KEY not set")
        try:
            return {"success": True, "data": await self.exa.answer(query, text=text)}
        except Exception as exc:  # noqa: BLE001
            return _failure(str(exc))

    async def _run_search(self, calls: list[tuple[str, SearchCall]], limit: int) -> dict:
        if not calls:
            return _failure("no configured providers for this search tool")
        tasks = [call() for _, call in calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok: list[list[SearchItem]] = []
        errors: dict[str, str] = {}
        for (name, _), res in zip(calls, results):
            if isinstance(res, Exception):
                errors[name] = str(res)
                continue
            ok.append(res)
        if not ok:
            return _failure("all providers failed", metadata={"errors": errors})
        merged = merge_search_results(ok, limit)
        return {"success": True, "data": {"web": merged}, "metadata": {"errors": errors}}

    # ---------- extract envelope ----------

    async def web_extract(self, urls: list[str]) -> dict:
        if len(urls) > self.cfg.max_urls:
            return _failure(f"too many URLs: max {self.cfg.max_urls}")
        results: list[ExtractItem] = []
        for url in urls:
            try:
                await asyncio.to_thread(validate_url, url)
                item = await asyncio.wait_for(
                    self._extract_one(url), timeout=self.cfg.extract_timeout
                )
            except UnsafeUrlError as exc:
                item = ExtractItem(url=url, error=str(exc))
            except TimeoutError:
                item = ExtractItem(url=url, error="extract timeout")
            results.append(item)
        return {"success": True, "data": _extract_items_to_dicts(results, self.cfg)}

    async def _extract_one(self, url: str) -> ExtractItem:
        chain = self._extract_chain(url)
        last_error = "no extractor configured"
        for extractor in chain:
            try:
                items = await extractor([url])
                item = items[0] if items else ExtractItem(url=url, error="empty extractor response")
            except Exception as exc:  # noqa: BLE001 - extract envelope must not raise
                item = ExtractItem(url=url, error=str(exc))
            if not item.error:
                return item
            last_error = item.error
        return ExtractItem(url=url, error=last_error)

    def _extract_chain(self, url: str) -> list[Callable[[list[str]], Awaitable[list[ExtractItem]]]]:
        chain: list[Callable[[list[str]], Awaitable[list[ExtractItem]]]] = []
        if is_document_url(url) and self.mineru.available():
            chain.append(self.mineru.extract)
        if self.firecrawl.available():
            chain.append(self.firecrawl.extract)
        if self.tavily.available():
            chain.append(self.tavily.extract)
        return chain


def _entity_category(entity_type: str) -> str | None:
    return {
        "people": "people",
        "company": "company",
        "financial": "financial report",
        "auto": None,
        "": None,
    }.get((entity_type or "auto").lower(), None)


def _failure(error: str, metadata: dict[str, Any] | None = None) -> dict:
    out = {"success": False, "error": error}
    if metadata:
        out["metadata"] = metadata
    return out


def _extract_items_to_dicts(items: list[ExtractItem], cfg: Config) -> list[dict]:
    total = 0
    out: list[dict] = []
    for item in items:
        content = item.content or ""
        raw = item.raw_content or content
        meta = dict(item.metadata or {})
        if len(content) > cfg.max_content_chars:
            content = content[: cfg.max_content_chars]
            meta["truncated"] = True
            meta["content_truncated"] = True
        if total + len(content) > cfg.max_total_chars:
            remaining = max(0, cfg.max_total_chars - total)
            content = content[:remaining]
            meta["truncated"] = True
            meta["total_truncated"] = True
        total += len(content)
        raw_limit = min(cfg.max_content_chars, max(0, cfg.max_total_chars - total))
        if len(raw) > raw_limit:
            raw = raw[:raw_limit]
            meta["truncated"] = True
            meta["raw_truncated"] = True
        d = {
            "url": item.url,
            "title": item.title,
            "content": content,
            "raw_content": raw,
            "metadata": meta,
        }
        if item.error:
            d["error"] = item.error
        out.append(d)
    return out
