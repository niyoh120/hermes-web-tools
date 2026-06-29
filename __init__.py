"""Hermes plugin root entrypoint.

Hermes clones plugins into ~/.hermes/plugins/<name> and requires an
__init__.py at that directory root. The actual implementation lives in the
hermes_web_tools package.
"""


def register(ctx):
    """Register the plugin from the implementation package."""
    from .hermes_web_tools import register as register_impl

    return register_impl(ctx)


__all__ = ["register"]
