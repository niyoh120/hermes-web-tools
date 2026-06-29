"""Grok backend — search via an OpenAI-compatible grok2api endpoint.

We ask the model to return a JSON list of ``{title, url, description}`` for
realtime / X-Twitter content. Grok URLs are LLM-generated and may be wrong, so
every URL is structurally validated; each result is stamped with
``provider="grok"`` and ``{"generated_by_llm": true}`` in ``extra`` so downstream
ranking can deprioritize uncorroborated hits.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import Config
from ..url_utils import is_valid_http_url
from .base import BackendError, SearchItem, request_json

_SYSTEM_PROMPT = (
    "You are a web-search assistant. For the user's query, return up to the "
    "requested number of real, currently-reachable web results as a JSON array. "
    'Each element: {"title": str, "url": str, "description": str}. '
    "Only include URLs that genuinely exist (prefer x.com / twitter.com, news "
    "sites, and official sources for realtime/news queries). Output ONLY the "
    "JSON array — no prose, no markdown fences."
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class GrokBackend:
    name = "grok"

    def __init__(self, cfg: Config, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self._client = client

    def available(self) -> bool:
        return self.cfg.has_grok

    async def search(self, query: str, limit: int = 5) -> list[SearchItem]:
        if not self.available():
            raise BackendError("unavailable", "GROK_API_URL/GROK_API_KEY not set")
        safe_query = " ".join(query.replace("\r", " ").replace("\n", " ").split())[:2000]
        body = {
            "model": self.cfg.grok_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"{safe_query}\n\nReturn up to {limit} results."},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.cfg.grok_api_key}"}
        client = self._client or httpx.AsyncClient()
        try:
            data = await request_json(
                client,
                "POST",
                f"{self.cfg.grok_api_url}/v1/chat/completions",
                headers=headers,
                json_body=body,
                timeout=self.cfg.search_timeout,
            )
        finally:
            if self._client is None:
                await client.aclose()
        content = _extract_content(data)
        raw_items = _parse_items(content)
        items: list[SearchItem] = []
        position = 0
        for r in raw_items:
            url = r.get("url", "")
            if not is_valid_http_url(url):
                continue  # drop fabricated / malformed URLs
            position += 1
            items.append(
                SearchItem(
                    title=str(r.get("title", "") or "")[:300],
                    url=url,
                    description=str(r.get("description", "") or "")[:500],
                    provider=self.name,
                    position=position,
                    extra={"generated_by_llm": True},
                )
            )
        return items


def _extract_content(data: dict[str, Any]) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise BackendError("parse", f"unexpected grok response shape: {exc}") from exc


def _parse_items(content: str) -> list[dict[str, Any]]:
    """Best-effort parse of an LLM JSON array, tolerant of fences/prose."""
    if not content:
        return []
    text = content.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_ARRAY_RE.search(text)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, dict)]
    return []
