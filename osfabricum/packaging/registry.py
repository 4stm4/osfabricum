"""Package builder registry.

Each builder module decorates its entry point with ``@register("package-name")``.
The coordinator calls ``get("package-name")`` to find the right builder without
any hardcoded dispatch table.

Adding a new package = create a new builder file with ``@register``, then
import it in ``osfabricum/packaging/__init__.py``.  No other code changes needed.
"""

from __future__ import annotations

from typing import Any, Callable

BuilderFn = Callable[..., Any]

_REGISTRY: dict[str, BuilderFn] = {}


def register(name: str) -> Callable[[BuilderFn], BuilderFn]:
    """Decorator that registers a builder under *name*."""
    def decorator(fn: BuilderFn) -> BuilderFn:
        _REGISTRY[name] = fn
        return fn
    return decorator


def get(name: str) -> BuilderFn | None:
    """Return the builder for *name*, or None if not registered."""
    return _REGISTRY.get(name)


def registered_names() -> list[str]:
    return sorted(_REGISTRY.keys())
