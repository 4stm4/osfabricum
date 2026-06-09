"""Runtime Package Policy service (M38).

Decides whether packages may be installed inside the built OS.

Seven policies:

* ``immutable``       — rootfs is read-only; no package manager in the image.
* ``build-time``      — PM used at build time only; not baked into the image.
* ``runtime-install`` — PM present; packages may be installed at runtime.
* ``signed-only``     — runtime installs must come from signed sources.
* ``feed-enabled``    — runtime installs only from registered M37 feeds.
* ``overlay-rootfs``  — writable overlayfs on top of an immutable rootfs + PM.
* ``offline-only``    — PM present but no network; only bundled packages.

Six backends are seeded at migration time (none / osf-pkg / opkg / apk / dpkg /
rpm).  The ``none`` backend is the only valid choice for ``immutable`` and the
default for ``build-time``.

:func:`render_policy` expands the backend's ``config_template`` against the
attached M37 feed records and stores the result on the policy row.  The
rendered text is deterministic for the same inputs (same pattern as
``plan_hash`` / ``index_hash``).
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime as _dt
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    PackageFeed,
    RuntimePackageBackend,
    RuntimePackagePolicy,
)
from osfabricum.db.session import sync_session

VALID_POLICIES = (
    "immutable",
    "build-time",
    "runtime-install",
    "signed-only",
    "feed-enabled",
    "overlay-rootfs",
    "offline-only",
)

# Policies that must not use a real PM backend.
_NO_PM_POLICIES = ("immutable",)
# Policies that require a non-"none" backend.
_NEEDS_PM_POLICIES = (
    "runtime-install",
    "signed-only",
    "feed-enabled",
    "overlay-rootfs",
    "offline-only",
)


def _now_utc() -> _dt:
    return _dt.now(UTC).replace(tzinfo=None)


def _policy_to_dict(p: RuntimePackagePolicy) -> dict[str, Any]:
    return {
        "id": p.id,
        "profile_id": p.profile_id,
        "policy": p.policy,
        "backend_name": p.backend_name,
        "feed_ids": p.feed_ids,
        "config_path": p.config_path,
        "rendered_config": p.rendered_config,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def list_backends(*, db_url: str | None = None) -> list[dict[str, Any]]:
    """Return all seeded package manager backends."""
    with sync_session(db_url) as s:
        return [
            {"id": b.id, "name": b.name, "description": b.description}
            for b in s.scalars(
                select(RuntimePackageBackend).order_by(RuntimePackageBackend.name)
            ).all()
        ]


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------


def get_policy(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Return the runtime policy for *profile_id*. Raises if none set."""
    with sync_session(db_url) as s:
        p = s.scalars(
            select(RuntimePackagePolicy).where(
                RuntimePackagePolicy.profile_id == profile_id
            )
        ).first()
        if p is None:
            raise ValueError(f"no runtime policy set for profile {profile_id!r}")
        return _policy_to_dict(p)


def set_policy(
    profile_id: str,
    policy: str,
    backend_name: str = "none",
    *,
    feed_ids: list[str] | None = None,
    config_path: str = "/etc/package-manager.conf",
    db_url: str | None = None,
) -> dict[str, Any]:
    """Create or replace the runtime package policy for *profile_id*.

    Validation rules:
    * *policy* must be one of the seven recognised values.
    * ``immutable`` requires ``backend_name="none"``.
    * ``runtime-install``, ``signed-only``, ``feed-enabled``, ``overlay-rootfs``,
      ``offline-only`` require a non-``none`` backend.
    * *backend_name* must be present in ``runtime_package_backends``.
    """
    if policy not in VALID_POLICIES:
        raise ValueError(
            f"unknown policy {policy!r}; valid: {', '.join(VALID_POLICIES)}"
        )
    with sync_session(db_url) as s:
        backend = s.scalars(
            select(RuntimePackageBackend).where(RuntimePackageBackend.name == backend_name)
        ).first()
        if backend is None:
            raise ValueError(f"unknown backend {backend_name!r}")

        if policy in _NO_PM_POLICIES and backend_name != "none":
            raise ValueError(
                f"policy {policy!r} requires backend 'none', got {backend_name!r}"
            )
        if policy in _NEEDS_PM_POLICIES and backend_name == "none":
            raise ValueError(
                f"policy {policy!r} requires a package-manager backend, not 'none'"
            )

        existing = s.scalars(
            select(RuntimePackagePolicy).where(
                RuntimePackagePolicy.profile_id == profile_id
            )
        ).first()

        now = _now_utc()
        if existing is not None:
            existing.policy = policy
            existing.backend_name = backend_name
            existing.feed_ids = feed_ids or []
            existing.config_path = config_path
            existing.rendered_config = None  # invalidate stale render
            existing.rendered_at = None
            existing.updated_at = now
            s.commit()
            return _policy_to_dict(existing)

        row = RuntimePackagePolicy(
            profile_id=profile_id,
            policy=policy,
            backend_name=backend_name,
            feed_ids=feed_ids or [],
            config_path=config_path,
            created_at=now,
            updated_at=now,
        )
        s.add(row)
        s.commit()
        return _policy_to_dict(row)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_policy(profile_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Expand the backend config template and store the result.

    Template placeholders per feed entry:
    * ``{feed_name}`` — feed name
    * ``{feed_url}``  — conceptual ``osf-feed://{name}/{channel}`` URL
    * ``{channel}``   — feed channel

    For policies that carry no PM config (``immutable``, ``build-time``),
    the rendered config is an empty string.

    The function is idempotent: re-running with the same data produces the
    same output (same pattern as ``plan_hash`` / ``index_hash``).
    """
    with sync_session(db_url) as s:
        p = s.scalars(
            select(RuntimePackagePolicy).where(
                RuntimePackagePolicy.profile_id == profile_id
            )
        ).first()
        if p is None:
            raise ValueError(f"no runtime policy set for profile {profile_id!r}")

        backend = s.scalars(
            select(RuntimePackageBackend).where(RuntimePackageBackend.name == p.backend_name)
        ).first()
        template = backend.config_template if backend else ""

        if not template or p.policy in ("immutable", "build-time"):
            rendered = ""
        else:
            feeds = s.scalars(
                select(PackageFeed).where(PackageFeed.id.in_(p.feed_ids))
            ).all() if p.feed_ids else []

            if feeds:
                lines = []
                for feed in feeds:
                    feed_url = f"osf-feed://{feed.name}/{feed.channel}"
                    lines.append(
                        template.format(
                            feed_name=feed.name,
                            feed_url=feed_url,
                            channel=feed.channel,
                        )
                    )
                rendered = "".join(lines)
            else:
                # No feeds referenced — render a commented-out placeholder
                rendered = template.format(
                    feed_name="<feed-name>",
                    feed_url="osf-feed://<feed>/<channel>",
                    channel="stable",
                )

        now = _now_utc()
        p.rendered_config = rendered
        p.rendered_at = now
        p.updated_at = now
        s.commit()

        result = _policy_to_dict(p)
        result["rendered_config"] = rendered
        return result
