"""Override spike — verify Hermes registry honors ``override=True``.

This runs only when the real ``hermes-agent`` package is importable (the user's
runtime environment). In this repo's isolated venv it is skipped via
``pytest.importorskip``. The test simulates the built-in ``web_search`` being
registered first, then our plugin overriding it, and asserts the handler and
schema are replaced while the toolset membership is preserved.

If this test ever fails against a real Hermes install, the fallback is to
rename our tools (e.g. ``web_search_plus``) instead of overriding — see the
plan's Risks / Rollback section.
"""

from __future__ import annotations

import pytest


def test_registry_override_replaces_handler():
    """override=True replaces a same-name tool from a different toolset."""
    pytest.importorskip("tools.registry")
    from tools.registry import registry  # type: ignore[import-not-found]

    builtin_handler = lambda args, **kw: '{"builtin": true}'  # noqa: E731
    plugin_handler = lambda args, **kw: '{"plugin": true}'  # noqa: E731
    name = "spike_override_probe"

    # Simulate built-in registration in toolset "web".
    registry.register(
        name=name,
        toolset="web",
        schema={"name": name, "description": "builtin", "parameters": {}},
        handler=builtin_handler,
    )
    entry = registry._tools.get(name)
    assert entry is not None and entry.handler is builtin_handler

    # Plugin overrides in the SAME toolset (keeps "web" toolset membership).
    registry.register(
        name=name,
        toolset="web",
        schema={"name": name, "description": "plugin", "parameters": {}},
        handler=plugin_handler,
        override=True,
    )
    entry = registry._tools.get(name)
    assert entry is not None
    assert entry.handler is plugin_handler, "override=True did not replace handler"
    assert entry.toolset == "web", "toolset membership must be preserved"
    assert entry.schema["description"] == "plugin", "schema not replaced"

    registry.deregister(name)


def test_registry_rejects_shadow_without_override():
    """Without override, a different-toolset shadow registration is rejected."""
    pytest.importorskip("tools.registry")
    from tools.registry import registry  # type: ignore[import-not-found]

    first = lambda args, **kw: '{"first": true}'  # noqa: E731
    shadow = lambda args, **kw: '{"shadow": true}'  # noqa: E731
    name = "spike_shadow_probe"

    registry.register(
        name=name,
        toolset="web",
        schema={"name": name, "description": "first", "parameters": {}},
        handler=first,
    )
    # Different toolset, no override -> rejected, original handler stays.
    registry.register(
        name=name,
        toolset="other",
        schema={"name": name, "description": "shadow", "parameters": {}},
        handler=shadow,
    )
    entry = registry._tools.get(name)
    assert entry is not None and entry.handler is first, "shadow should be rejected"
    assert entry.toolset == "web"

    registry.deregister(name)
