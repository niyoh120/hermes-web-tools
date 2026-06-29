"""Integration-ish register(ctx) tests with a fake PluginContext."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import hermes_web_tools


class FakeCtx:
    def __init__(self):
        self.calls = []

    def register_tool(self, **kwargs):
        self.calls.append(kwargs)


def test_register_registers_seven_web_tools():
    ctx = FakeCtx()
    hermes_web_tools.register(ctx)
    names = [c["name"] for c in ctx.calls]
    assert names == [
        "web_search",
        "web_search_realtime",
        "web_search_research",
        "web_search_code",
        "web_search_entities",
        "web_answer",
        "web_extract",
    ]
    assert all(c["toolset"] == "web" for c in ctx.calls)
    assert all(c["is_async"] is True for c in ctx.calls)
    assert {c["name"] for c in ctx.calls if c["override"]} == {"web_search", "web_extract"}
    assert all(callable(c["handler"]) for c in ctx.calls)
    assert all(callable(c["check_fn"]) for c in ctx.calls)


def test_register_schema_names_match_tool_names():
    ctx = FakeCtx()
    hermes_web_tools.register(ctx)
    for call in ctx.calls:
        assert call["schema"]["name"] == call["name"]
        assert call["description"] == call["schema"]["description"]


def test_plugin_root_entrypoint_exports_register():
    root_init = Path(__file__).resolve().parents[1] / "__init__.py"
    spec = importlib.util.spec_from_file_location("hermes_web_tools_plugin_root", root_init)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.register is hermes_web_tools.register
