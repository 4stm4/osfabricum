"""Business logic for M68 — Build Isolation / Sandbox Policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import (
    IsolationPolicy,
    RecipeIsolationRequirement,
    _now,
    _uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_MODES: frozenset[str] = frozenset(
    {"none", "chroot", "bubblewrap", "nspawn", "podman", "firecracker", "vm"}
)
VALID_WRITE_ACCESS: frozenset[str] = frozenset({"none", "build-dir", "full"})
VALID_CACHE_MODES: frozenset[str] = frozenset({"ro", "rw", "none"})

MODE_ORDER = ["none", "chroot", "bubblewrap", "nspawn", "podman", "firecracker", "vm"]


def create_isolation_policy(
    session: "Session",
    name: str,
    mode: str = "none",
    label: str = "",
    description: str = "",
    network_allowed: bool = True,
    write_access: str = "build-dir",
    cache_mode: str = "ro",
    secret_access: bool = False,
    privileged: bool = False,
) -> IsolationPolicy:
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode {mode!r}. Valid: {sorted(VALID_MODES)}")
    if write_access not in VALID_WRITE_ACCESS:
        raise ValueError(f"Invalid write_access {write_access!r}")
    if cache_mode not in VALID_CACHE_MODES:
        raise ValueError(f"Invalid cache_mode {cache_mode!r}")
    policy = IsolationPolicy(
        id=_uuid(), name=name, label=label, description=description,
        mode=mode, network_allowed=network_allowed, write_access=write_access,
        cache_mode=cache_mode, secret_access=secret_access, privileged=privileged,
        created_at=_now(), updated_at=_now(),
    )
    session.add(policy)
    session.flush()
    return policy


def list_isolation_policies(session: "Session") -> list[IsolationPolicy]:
    return list(
        session.scalars(select(IsolationPolicy).order_by(IsolationPolicy.name)).all()
    )


def get_isolation_policy(session: "Session", policy_id: str) -> IsolationPolicy:
    p = session.get(IsolationPolicy, policy_id)
    if p is None:
        raise KeyError(f"IsolationPolicy {policy_id!r} not found")
    return p


def get_isolation_policy_by_name(
    session: "Session", name: str
) -> IsolationPolicy | None:
    return session.scalars(
        select(IsolationPolicy).where(IsolationPolicy.name == name)
    ).first()


def update_isolation_policy(
    session: "Session",
    policy_id: str,
    mode: str | None = None,
    network_allowed: bool | None = None,
    write_access: str | None = None,
    cache_mode: str | None = None,
    secret_access: bool | None = None,
    privileged: bool | None = None,
) -> IsolationPolicy:
    policy = get_isolation_policy(session, policy_id)
    if mode is not None:
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid mode {mode!r}. Valid: {sorted(VALID_MODES)}")
        policy.mode = mode
    if network_allowed is not None:
        policy.network_allowed = network_allowed
    if write_access is not None:
        if write_access not in VALID_WRITE_ACCESS:
            raise ValueError(f"Invalid write_access {write_access!r}")
        policy.write_access = write_access
    if cache_mode is not None:
        if cache_mode not in VALID_CACHE_MODES:
            raise ValueError(f"Invalid cache_mode {cache_mode!r}")
        policy.cache_mode = cache_mode
    if secret_access is not None:
        policy.secret_access = secret_access
    if privileged is not None:
        policy.privileged = privileged
    policy.updated_at = _now()
    session.flush()
    return policy


def add_recipe_requirement(
    session: "Session",
    required_mode: str,
    recipe_id: str | None = None,
    reason: str = "",
) -> RecipeIsolationRequirement:
    if required_mode not in VALID_MODES:
        raise ValueError(f"Invalid required_mode {required_mode!r}. Valid: {sorted(VALID_MODES)}")
    req = RecipeIsolationRequirement(
        id=_uuid(), recipe_id=recipe_id, required_mode=required_mode,
        reason=reason, created_at=_now(),
    )
    session.add(req)
    session.flush()
    return req


def list_recipe_requirements(
    session: "Session", recipe_id: str | None = None
) -> list[RecipeIsolationRequirement]:
    q = select(RecipeIsolationRequirement).order_by(
        RecipeIsolationRequirement.required_mode
    )
    if recipe_id is not None:
        q = q.where(RecipeIsolationRequirement.recipe_id == recipe_id)
    return list(session.scalars(q).all())


def policy_satisfies(policy: IsolationPolicy, required_mode: str) -> bool:
    """Return True if policy's mode is at least as strong as required_mode."""
    try:
        policy_level = MODE_ORDER.index(policy.mode)
        required_level = MODE_ORDER.index(required_mode)
    except ValueError:
        return False
    return policy_level >= required_level
