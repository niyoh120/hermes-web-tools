"""Tool handlers and check functions.

Handlers are async and return JSON strings, as Hermes expects. ``register`` uses
``is_async=True`` for all of them.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from .config import load_config
from .router import ToolRouter


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _failure(message: str) -> str:
    return _json({"success": False, "error": message})


def _query(args: dict[str, Any]) -> str:
    query = args.get("query", "")
    return query.strip() if isinstance(query, str) else ""


def _limit(args: dict[str, Any]) -> int:
    raw = args.get("limit", 5)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, 100))


def _max_tokens(args: dict[str, Any]) -> int | None:
    raw = args.get("max_tokens")
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(50, min(value, 100_000))


_ROUTER: ToolRouter | None = None


def _router() -> ToolRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = ToolRouter(load_config())
    return _ROUTER


def _bool_arg(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


async def _safe(name: str, op: Callable[[], Awaitable[dict]]) -> str:
    try:
        return _json(await op())
    except Exception:  # noqa: BLE001 - Hermes tools must return JSON strings
        return _failure(f"{name}: internal error")


# ---------- handlers ----------


async def web_search(args: dict[str, Any], **_kwargs) -> str:
    query = _query(args)
    if not query:
        return _failure("query is required")
    return await _safe("web_search", lambda: _router().web_search(query, limit=_limit(args)))


async def web_search_realtime(args: dict[str, Any], **_kwargs) -> str:
    query = _query(args)
    if not query:
        return _failure("query is required")
    return await _safe(
        "web_search_realtime", lambda: _router().web_search_realtime(query, limit=_limit(args))
    )


async def web_search_research(args: dict[str, Any], **_kwargs) -> str:
    query = _query(args)
    if not query:
        return _failure("query is required")
    return await _safe(
        "web_search_research", lambda: _router().web_search_research(query, limit=_limit(args))
    )


async def web_search_code(args: dict[str, Any], **_kwargs) -> str:
    query = _query(args)
    if not query:
        return _failure("query is required")
    return await _safe(
        "web_search_code", lambda: _router().web_search_code(query, max_tokens=_max_tokens(args))
    )


async def web_search_entities(args: dict[str, Any], **_kwargs) -> str:
    query = _query(args)
    if not query:
        return _failure("query is required")
    entity_type = args.get("entity_type", "auto")
    if not isinstance(entity_type, str):
        entity_type = "auto"
    return await _safe(
        "web_search_entities",
        lambda: _router().web_search_entities(query, limit=_limit(args), entity_type=entity_type),
    )


async def web_answer(args: dict[str, Any], **_kwargs) -> str:
    query = _query(args)
    if not query:
        return _failure("query is required")
    text = _bool_arg(args.get("text", True))
    return await _safe("web_answer", lambda: _router().web_answer(query, text=text))


async def web_extract(args: dict[str, Any], **_kwargs) -> str:
    urls = args.get("urls")
    if not isinstance(urls, list) or not urls:
        return _failure("urls must be a non-empty list")
    clean_urls = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    if not clean_urls:
        return _failure("urls must contain at least one URL string")
    return await _safe("web_extract", lambda: _router().web_extract(clean_urls))


# ---------- check_fn ----------


def check_web_search() -> bool:
    cfg = load_config()
    return cfg.has_exa or cfg.has_tavily


def check_web_search_realtime() -> bool:
    return load_config().has_grok


def check_web_search_research() -> bool:
    cfg = load_config()
    return cfg.has_exa or cfg.has_tavily


def check_web_search_code() -> bool:
    return load_config().has_exa


def check_web_search_entities() -> bool:
    cfg = load_config()
    return cfg.has_exa or cfg.has_tavily


def check_web_answer() -> bool:
    return load_config().has_exa


def check_web_extract() -> bool:
    cfg = load_config()
    return cfg.has_firecrawl or cfg.has_tavily or cfg.has_mineru
