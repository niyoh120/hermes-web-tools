"""hermes-web-tools — multi-provider web tools for Hermes agent.

This is a *general tool plugin*. It intentionally overrides Hermes' built-in
``web_search`` and ``web_extract`` tool handlers via ``ctx.register_tool(...,
override=True)`` and adds specialized category tools for the model to choose.
"""

from __future__ import annotations

import logging

from . import handlers, schemas

logger = logging.getLogger(__name__)

_TOOLSET = "web"

_TOOLS = [
    ("web_search", schemas.WEB_SEARCH, handlers.web_search, handlers.check_web_search, True),
    (
        "web_search_realtime",
        schemas.WEB_SEARCH_REALTIME,
        handlers.web_search_realtime,
        handlers.check_web_search_realtime,
        False,
    ),
    (
        "web_search_research",
        schemas.WEB_SEARCH_RESEARCH,
        handlers.web_search_research,
        handlers.check_web_search_research,
        False,
    ),
    (
        "web_search_code",
        schemas.WEB_SEARCH_CODE,
        handlers.web_search_code,
        handlers.check_web_search_code,
        False,
    ),
    (
        "web_search_entities",
        schemas.WEB_SEARCH_ENTITIES,
        handlers.web_search_entities,
        handlers.check_web_search_entities,
        False,
    ),
    ("web_answer", schemas.WEB_ANSWER, handlers.web_answer, handlers.check_web_answer, False),
    ("web_extract", schemas.WEB_EXTRACT, handlers.web_extract, handlers.check_web_extract, True),
]


def register(ctx) -> None:
    """Plugin entry point called once by Hermes."""
    registered = 0
    for name, schema, handler, check_fn, override in _TOOLS:
        try:
            ctx.register_tool(
                name=name,
                toolset=_TOOLSET,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                is_async=True,
                description=schema.get("description", ""),
                override=override,
            )
            registered += 1
        except Exception as exc:  # noqa: BLE001 - keep remaining tools available
            logger.warning("[hermes-web-tools] failed to register %s: %s", name, exc)
    logger.info(
        "[hermes-web-tools] attempted %d web tool registrations (%d succeeded)",
        len(_TOOLS),
        registered,
    )
