"""Tests for config parsing — bools, int defaults, availability."""

from __future__ import annotations

from hermes_web_tools.config import Config, load_config


def test_defaults_when_env_empty(monkeypatch):
    for var in [
        "EXA_API_KEY",
        "EXA_BASE_URL",
        "TAVILY_API_KEY",
        "TAVILY_BASE_URL",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_BASE_URL",
        "GROK_API_URL",
        "GROK_API_KEY",
        "MINERU_API_TOKEN",
        "MINERU_BASE_URL",
        "MINERU_AGENT_FALLBACK_ENABLED",
        "HERMES_WEB_TOOLS_SEARCH_TIMEOUT",
        "HERMES_WEB_TOOLS_EXTRACT_TIMEOUT",
        "HERMES_WEB_TOOLS_HEAD_TIMEOUT",
        "HERMES_WEB_TOOLS_MAX_URLS",
        "HERMES_WEB_TOOLS_MAX_CONTENT_CHARS",
        "HERMES_WEB_TOOLS_MAX_TOTAL_CHARS",
        "GROK_MODEL",
        "MINERU_MODEL_VERSION",
    ]:
        monkeypatch.delenv(var, raising=False)
    cfg = load_config()
    assert cfg.exa_api_key == ""
    assert cfg.tavily_api_key == ""
    assert cfg.has_exa is False
    assert cfg.has_tavily is False
    assert cfg.has_firecrawl is False
    assert cfg.has_grok is False
    assert cfg.has_mineru is False
    assert cfg.search_timeout == 15
    assert cfg.max_urls == 10


def test_base_urls(monkeypatch):
    monkeypatch.setenv("EXA_BASE_URL", "https://exa.local/")
    monkeypatch.setenv("TAVILY_BASE_URL", "https://tavily.local/")
    monkeypatch.setenv("FIRECRAWL_BASE_URL", "https://fire.local/")
    monkeypatch.setenv("MINERU_BASE_URL", "https://mineru.local/")
    cfg = load_config()
    assert cfg.exa_base_url == "https://exa.local"
    assert cfg.tavily_base_url == "https://tavily.local"
    assert cfg.firecrawl_base_url == "https://fire.local"
    assert cfg.mineru_base_url == "https://mineru.local"


def test_tavily_single_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "key1")
    cfg = load_config()
    assert cfg.tavily_api_key == "key1"
    assert cfg.has_tavily is True


def test_config_repr_hides_keys_and_clamps_limits():
    cfg = Config(exa_api_key="secret", tavily_api_key="t1", max_content_chars=10, max_total_chars=5)
    text = repr(cfg)
    assert "secret" not in text and "t1" not in text
    assert cfg.max_content_chars == 5


def test_bool_env_variants(monkeypatch):
    for val in ("true", "TRUE", "1", "yes", "on"):
        monkeypatch.setenv("MINERU_AGENT_FALLBACK_ENABLED", val)
        assert load_config().mineru_agent_fallback_enabled is True, val
    for val in ("false", "0", "off", ""):
        monkeypatch.setenv("MINERU_AGENT_FALLBACK_ENABLED", val)
        assert load_config().mineru_agent_fallback_enabled is False, val


def test_int_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("HERMES_WEB_TOOLS_SEARCH_TIMEOUT", "not-a-number")
    assert load_config().search_timeout == 15
    monkeypatch.setenv("HERMES_WEB_TOOLS_SEARCH_TIMEOUT", "0")
    assert load_config().search_timeout == 15  # below minimum -> default
    monkeypatch.setenv("HERMES_WEB_TOOLS_SEARCH_TIMEOUT", "42")
    assert load_config().search_timeout == 42


def test_grok_requires_both_url_and_key(monkeypatch):
    monkeypatch.setenv("GROK_API_URL", "http://localhost:8000/")
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    assert load_config().has_grok is False
    monkeypatch.setenv("GROK_API_KEY", "k")
    cfg = load_config()
    assert cfg.has_grok is True
    assert cfg.grok_api_url == "http://localhost:8000"  # trailing slash stripped


def test_mineru_availability_token_or_fallback(monkeypatch):
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    monkeypatch.delenv("MINERU_AGENT_FALLBACK_ENABLED", raising=False)
    assert load_config().has_mineru is False
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    assert load_config().has_mineru is True
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    monkeypatch.setenv("MINERU_AGENT_FALLBACK_ENABLED", "true")
    assert load_config().has_mineru is True
