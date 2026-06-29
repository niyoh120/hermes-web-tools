"""Hermes plugin root entrypoint.

Hermes clones plugins into ~/.hermes/plugins/<name> and requires an
__init__.py at that directory root. The actual implementation lives in the
hermes_web_tools package.
"""

from hermes_web_tools import register

__all__ = ["register"]
