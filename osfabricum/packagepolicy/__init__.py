"""Runtime Package Policy (M38).

Determines whether packages may be installed inside the built OS image and
which package manager backend (if any) is baked in.
"""

from __future__ import annotations

from osfabricum.packagepolicy.service import (
    VALID_POLICIES,
    get_policy,
    list_backends,
    render_policy,
    set_policy,
)

__all__ = [
    "VALID_POLICIES",
    "get_policy",
    "list_backends",
    "render_policy",
    "set_policy",
]
