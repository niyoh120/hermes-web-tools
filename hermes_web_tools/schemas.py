"""Tool schemas — what Hermes' LLM sees.

Descriptions are intentionally explicit: routing is now done by the model's
tool choice, so schema text is the main guidance.
"""

from __future__ import annotations

_LIMIT = {
    "type": "integer",
    "description": "Maximum number of web results to return. Defaults to 5. Valid range: 1-100.",
    "default": 5,
    "minimum": 1,
    "maximum": 100,
}

_QUERY = {"type": "string", "description": "The search query or question."}

WEB_SEARCH = {
    "name": "web_search",
    "description": (
        "General-purpose web search. Use for broad factual lookup, normal web pages, "
        "product/docs pages, and queries that do not clearly fit realtime, research, code, "
        "entities, or direct answer tools. Returns a ranked list of web results."
    ),
    "parameters": {
        "type": "object",
        "properties": {"query": _QUERY, "limit": _LIMIT},
        "required": ["query"],
    },
}

WEB_SEARCH_REALTIME = {
    "name": "web_search_realtime",
    "description": (
        "Search for current events, breaking news, trending topics, or X/Twitter-related "
        "information. Uses Grok. Returns a ranked list of web results."
    ),
    "parameters": {
        "type": "object",
        "properties": {"query": _QUERY, "limit": _LIMIT},
        "required": ["query"],
    },
}

WEB_SEARCH_RESEARCH = {
    "name": "web_search_research",
    "description": (
        "Search for academic papers, arXiv, studies, technical reports, and deep research "
        "sources. Use when the user wants evidence, citations, or scholarly material. "
        "Returns a ranked list of web results."
    ),
    "parameters": {
        "type": "object",
        "properties": {"query": _QUERY, "limit": _LIMIT},
        "required": ["query"],
    },
}

WEB_SEARCH_CODE = {
    "name": "web_search_code",
    "description": (
        "Search for code examples and implementation context across GitHub, documentation, "
        "Stack Overflow, and related technical sources. Use for programming/API usage questions. "
        "Returns token-efficient code context text, not a web-result list."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": _QUERY,
            "max_tokens": {
                "type": "integer",
                "description": "Optional token budget for returned code context. Omit for dynamic sizing.",
                "minimum": 50,
                "maximum": 100000,
            },
        },
        "required": ["query"],
    },
}

WEB_SEARCH_ENTITIES = {
    "name": "web_search_entities",
    "description": (
        "Search for people, company, startup, funding, earnings, SEC filing, or financial-report "
        "information. Use entity_type to guide the entity category. Returns a ranked list of web results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": _QUERY,
            "limit": _LIMIT,
            "entity_type": {
                "type": "string",
                "enum": ["auto", "people", "company", "financial"],
                "description": (
                    "Entity category hint. Use people for person/profile lookups, company for "
                    "companies/startups/funding, financial for earnings/SEC/annual reports, auto if unsure."
                ),
                "default": "auto",
            },
        },
        "required": ["query"],
    },
}

WEB_ANSWER = {
    "name": "web_answer",
    "description": (
        "Ask Exa for a grounded answer with citations. Use when the user wants a direct answer or "
        "summary with cited sources, rather than a list of search results. Returns answer + citations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": _QUERY,
            "text": {
                "type": "boolean",
                "description": "Whether citations should include supporting text. Defaults to true.",
                "default": True,
            },
        },
        "required": ["query"],
    },
}

WEB_EXTRACT = {
    "name": "web_extract",
    "description": (
        "Extract readable content from one or more URLs. Use after search when you need page/document "
        "content. Handles web pages and documents (PDF/Office/images). Returns markdown-like content."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string", "format": "uri"},
                "description": "HTTP/HTTPS URLs to extract. Maximum 10 URLs.",
                "minItems": 1,
                "maxItems": 10,
            }
        },
        "required": ["urls"],
    },
}

ALL_SCHEMAS = [
    WEB_SEARCH,
    WEB_SEARCH_REALTIME,
    WEB_SEARCH_RESEARCH,
    WEB_SEARCH_CODE,
    WEB_SEARCH_ENTITIES,
    WEB_ANSWER,
    WEB_EXTRACT,
]
