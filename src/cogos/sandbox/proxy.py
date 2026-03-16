"""Proxy helpers for capability namespaces.

Provides CapabilityProxy (a dynamic attribute/method wrapper) and
make_namespace_proxy (a simple name-assignment wrapper used for MVP).
"""

from __future__ import annotations

from typing import Any, Callable


class CapabilityProxy:
    """Base proxy object returned by capability calls.

    Attributes are set dynamically from the result content.
    Methods are stored in a dict and returned via __getattr__.
    """

    def __init__(self, content: dict[str, Any] | None = None, methods: dict[str, Callable] | None = None) -> None:
        self._content = content or {}
        self._methods = methods or {}
        for key, value in self._content.items():
            if not key.startswith("_"):
                setattr(self, key, value)

    def __repr__(self) -> str:
        return f"<Proxy {self._content}>"

    def __getattr__(self, name: str) -> Any:
        if name in self._methods:
            return self._methods[name]
        raise AttributeError(f"Proxy has no attribute or method '{name}'")


def make_namespace_proxy(name: str, handler: Callable) -> Callable:
    """Attach *name* to *handler* and return it as-is.

    For the MVP, capabilities are exposed as simple callables rather than
    namespace objects with multiple methods.
    """
    proxy = handler
    proxy.__name__ = name
    return proxy
