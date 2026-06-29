"""Merge and deduplicate normalized search results."""

from __future__ import annotations

from dataclasses import dataclass, field

from .backends.base import SearchItem
from .url_utils import normalize_url


@dataclass
class _Merged:
    title: str
    url: str
    description: str
    best_position: int
    sources: set[str] = field(default_factory=set)
    provider_positions: dict[str, int] = field(default_factory=dict)
    provider_extras: dict[str, dict] = field(default_factory=dict)

    @property
    def source_count(self) -> int:
        return len(self.sources)


def merge_search_results(result_lists: list[list[SearchItem]], limit: int) -> list[dict]:
    """Merge provider result lists into Hermes-compatible web entries.

    Sorting: more sources first, then best original provider position. Returned
    positions are reassigned 1..n after sorting.
    """
    merged: dict[str, _Merged] = {}
    for results in result_lists:
        for item in results:
            if not item.url:
                continue
            key = normalize_url(item.url)
            position = item.position if item.position > 0 else 9999
            if key not in merged:
                merged[key] = _Merged(
                    title=item.title,
                    url=item.url,
                    description=item.description,
                    best_position=position,
                )
            cur = merged[key]
            provider = item.provider or "unknown"
            cur.sources.add(provider)
            cur.provider_positions[provider] = min(
                position, cur.provider_positions.get(provider, position)
            )
            if item.extra:
                cur.provider_extras[provider] = item.extra
            cur.best_position = min(cur.best_position, position)
            # Prefer richer title / description while keeping the first URL.
            if len(item.title or "") > len(cur.title or ""):
                cur.title = item.title
            if len(item.description or "") > len(cur.description or ""):
                cur.description = item.description

    sorted_items = sorted(merged.values(), key=lambda x: (-x.source_count, x.best_position))
    out: list[dict] = []
    for idx, item in enumerate(sorted_items[: max(0, limit)], start=1):
        provider_extras = item.provider_extras
        generated_by_llm = any(
            v.get("generated_by_llm") for v in provider_extras.values() if isinstance(v, dict)
        )
        out.append(
            {
                "title": item.title,
                "url": item.url,
                "description": item.description,
                "position": idx,
                "metadata": {
                    "sources": sorted(item.sources),
                    "source_count": item.source_count,
                    "provider_positions": item.provider_positions,
                    "provider_extras": provider_extras,
                    "generated_by_llm": generated_by_llm,
                },
            }
        )
    return out
