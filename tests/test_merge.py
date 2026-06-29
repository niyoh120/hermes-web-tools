"""Tests for merge — URL dedup, multi-source priority, position renumber."""

from __future__ import annotations

from hermes_web_tools.backends.base import SearchItem
from hermes_web_tools.merge import merge_search_results


def item(provider, pos, url, title="T", desc="d", extra=None):
    return SearchItem(
        title=title,
        url=url,
        description=desc,
        provider=provider,
        position=pos,
        extra=extra or {},
    )


def test_dedups_by_normalized_url():
    out = merge_search_results(
        [
            [item("exa", 1, "https://e.com/x?utm_source=a", title="Short")],
            [item("tavily", 3, "https://e.com/x", title="Longer title", desc="longer desc")],
        ],
        limit=5,
    )
    assert len(out) == 1
    assert out[0]["title"] == "Longer title"
    assert out[0]["description"] == "longer desc"
    assert out[0]["metadata"]["source_count"] == 2
    assert out[0]["metadata"]["sources"] == ["exa", "tavily"]
    assert out[0]["metadata"]["provider_positions"] == {"exa": 1, "tavily": 3}


def test_multi_source_priority_then_best_position():
    out = merge_search_results(
        [
            [item("exa", 1, "https://a.com"), item("exa", 2, "https://b.com")],
            [item("tavily", 5, "https://b.com"), item("tavily", 1, "https://c.com")],
        ],
        limit=10,
    )
    # b has two sources, then a/c tie source_count=1 sorted by best position.
    assert [o["url"] for o in out] == ["https://b.com", "https://a.com", "https://c.com"]


def test_limit_and_position_renumber():
    out = merge_search_results(
        [[item("exa", i, f"https://e.com/{i}") for i in range(1, 5)]], limit=2
    )
    assert [o["position"] for o in out] == [1, 2]
    assert len(out) == 2


def test_empty_urls_skipped():
    assert merge_search_results([[item("exa", 1, "")]], limit=5) == []


def test_generated_by_llm_metadata():
    out = merge_search_results(
        [[item("grok", 1, "https://x.com/a", extra={"generated_by_llm": True})]], limit=5
    )
    assert out[0]["metadata"]["generated_by_llm"] is True
    assert out[0]["metadata"]["provider_extras"]["grok"] == {"generated_by_llm": True}


def test_preserves_www_as_distinct():
    out = merge_search_results(
        [
            [item("exa", 1, "https://www.e.com/x")],
            [item("tavily", 1, "https://e.com/x")],
        ],
        limit=5,
    )
    assert len(out) == 2
