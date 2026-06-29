"""Configuration — reads environment variables once at load time.

All network-bearing tools self-gate via ``check_fn`` (see ``handlers.py``);
this module only exposes cheap primitives (env-var presence, parsed numbers,
credentials). No network calls happen here.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field

# Defaults are deliberately conservative; every value is overridable via env.
_DEFAULTS = {
    "search_timeout": 15,
    "extract_timeout": 120,
    "head_timeout": 3,
    "max_urls": 10,
    "max_content_chars": 50_000,
    "max_total_chars": 200_000,
    "grok_model": "grok-4.20-fast",
    "exa_base_url": "https://api.exa.ai",
    "tavily_base_url": "https://api.tavily.com",
    "firecrawl_base_url": "https://api.firecrawl.dev",
    "mineru_base_url": "https://mineru.net",
    "mineru_model_version": "vlm",
}

_TRUE = {"1", "true", "yes", "on"}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        warnings.warn(f"Invalid integer for {name}: {raw!r}; using default {default}", stacklevel=3)
        return default
    if value < minimum:
        warnings.warn(
            f"{name}={value} is below minimum {minimum}; using default {default}",
            stacklevel=3,
        )
        return default
    return value


@dataclass
class Config:
    # Provider credentials.
    exa_api_key: str = field(default="", repr=False)
    exa_base_url: str = field(default=_DEFAULTS["exa_base_url"], repr=False)
    tavily_api_key: str = field(default="", repr=False)
    tavily_base_url: str = field(default=_DEFAULTS["tavily_base_url"], repr=False)
    firecrawl_api_key: str = field(default="", repr=False)
    firecrawl_base_url: str = field(default=_DEFAULTS["firecrawl_base_url"], repr=False)
    grok_api_url: str = field(default="", repr=False)
    grok_api_key: str = field(default="", repr=False)
    grok_model: str = _DEFAULTS["grok_model"]
    mineru_api_token: str = field(default="", repr=False)
    mineru_base_url: str = field(default=_DEFAULTS["mineru_base_url"], repr=False)
    mineru_model_version: str = _DEFAULTS["mineru_model_version"]
    mineru_agent_fallback_enabled: bool = False

    # Timeouts (seconds).
    search_timeout: int = _DEFAULTS["search_timeout"]
    extract_timeout: int = _DEFAULTS["extract_timeout"]
    head_timeout: int = _DEFAULTS["head_timeout"]

    # Size limits.
    max_urls: int = _DEFAULTS["max_urls"]
    max_content_chars: int = _DEFAULTS["max_content_chars"]
    max_total_chars: int = _DEFAULTS["max_total_chars"]

    def __post_init__(self) -> None:
        if self.max_content_chars > self.max_total_chars:
            self.max_content_chars = self.max_total_chars

    # --- cheap availability flags (no network) ---
    @property
    def has_exa(self) -> bool:
        return bool(self.exa_api_key)

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def has_firecrawl(self) -> bool:
        return bool(self.firecrawl_api_key)

    @property
    def has_grok(self) -> bool:
        return bool(self.grok_api_url) and bool(self.grok_api_key)

    @property
    def has_mineru(self) -> bool:
        return bool(self.mineru_api_token) or self.mineru_agent_fallback_enabled


def load_config() -> Config:
    """Build a Config from the current process environment."""
    return Config(
        exa_api_key=os.getenv("EXA_API_KEY", "").strip(),
        exa_base_url=os.getenv("EXA_BASE_URL", _DEFAULTS["exa_base_url"]).strip().rstrip("/")
        or _DEFAULTS["exa_base_url"],
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        tavily_base_url=os.getenv("TAVILY_BASE_URL", _DEFAULTS["tavily_base_url"])
        .strip()
        .rstrip("/")
        or _DEFAULTS["tavily_base_url"],
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", "").strip(),
        firecrawl_base_url=os.getenv("FIRECRAWL_BASE_URL", _DEFAULTS["firecrawl_base_url"])
        .strip()
        .rstrip("/")
        or _DEFAULTS["firecrawl_base_url"],
        grok_api_url=os.getenv("GROK_API_URL", "").strip().rstrip("/"),
        grok_api_key=os.getenv("GROK_API_KEY", "").strip(),
        grok_model=os.getenv("GROK_MODEL", _DEFAULTS["grok_model"]).strip()
        or _DEFAULTS["grok_model"],
        mineru_api_token=os.getenv("MINERU_API_TOKEN", "").strip(),
        mineru_base_url=os.getenv("MINERU_BASE_URL", _DEFAULTS["mineru_base_url"])
        .strip()
        .rstrip("/")
        or _DEFAULTS["mineru_base_url"],
        mineru_model_version=os.getenv(
            "MINERU_MODEL_VERSION", _DEFAULTS["mineru_model_version"]
        ).strip()
        or _DEFAULTS["mineru_model_version"],
        mineru_agent_fallback_enabled=_bool_env("MINERU_AGENT_FALLBACK_ENABLED", False),
        search_timeout=_int_env("HERMES_WEB_TOOLS_SEARCH_TIMEOUT", _DEFAULTS["search_timeout"]),
        extract_timeout=_int_env("HERMES_WEB_TOOLS_EXTRACT_TIMEOUT", _DEFAULTS["extract_timeout"]),
        head_timeout=_int_env("HERMES_WEB_TOOLS_HEAD_TIMEOUT", _DEFAULTS["head_timeout"]),
        max_urls=_int_env("HERMES_WEB_TOOLS_MAX_URLS", _DEFAULTS["max_urls"]),
        max_content_chars=_int_env(
            "HERMES_WEB_TOOLS_MAX_CONTENT_CHARS", _DEFAULTS["max_content_chars"]
        ),
        max_total_chars=_int_env("HERMES_WEB_TOOLS_MAX_TOTAL_CHARS", _DEFAULTS["max_total_chars"]),
    )
