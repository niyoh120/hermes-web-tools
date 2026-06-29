"""Tests for tool schemas."""

from __future__ import annotations

from hermes_web_tools import schemas


def test_all_schemas_have_unique_names():
    names = [s["name"] for s in schemas.ALL_SCHEMAS]
    assert names == [
        "web_search",
        "web_search_realtime",
        "web_search_research",
        "web_search_code",
        "web_search_entities",
        "web_answer",
        "web_extract",
    ]
    assert len(names) == len(set(names))


def test_standard_search_limit_schema():
    for schema in [
        schemas.WEB_SEARCH,
        schemas.WEB_SEARCH_REALTIME,
        schemas.WEB_SEARCH_RESEARCH,
        schemas.WEB_SEARCH_ENTITIES,
    ]:
        limit = schema["parameters"]["properties"]["limit"]
        assert limit["minimum"] == 1
        assert limit["maximum"] == 100


def test_code_schema_returns_context_description():
    desc = schemas.WEB_SEARCH_CODE["description"].lower()
    assert "code context" in desc
    assert "not a web-result list" in desc


def test_answer_schema_mentions_citations():
    assert "citations" in schemas.WEB_ANSWER["description"].lower()


def test_extract_urls_bounded():
    urls = schemas.WEB_EXTRACT["parameters"]["properties"]["urls"]
    assert urls["maxItems"] == 10
    assert urls["items"]["type"] == "string"
