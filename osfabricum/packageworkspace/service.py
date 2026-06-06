"""Package Workspace / Package Manager service (M35).

Central manager of packages by **kind** and **layer**, reusable groups/sets, the
package **cache**, locks and feeds (closes G-04, G-28).

Two things are the heart:

* :func:`compute_cache_key` — a package cache key is *forbidden* from being
  ``name+version+arch``. It folds in source/recipe/feature/toolchain/ABI hashes
  and, for kernel-bound kinds (``kernel-module``/``driver``), the kernel release
  and config hash. A different ``.config`` therefore yields a different key —
  a kernel module is never silently reused across an incompatible kernel.
* :func:`explain_cache` / :func:`lookup_cache` — every hit/miss is *explained*:
  the key component that differs is reported.

:func:`resolve_set` expands a package set into a deterministic, layer-ordered
install plan and records it (artifact ``kind=install-plan``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select

from osfabricum.db.models import (
    Package,
    PackageCacheEntry,
    PackageCompatibility,
    PackageFeed,
    PackageFeedIndex,
    PackageGroup,
    PackageGroupMember,
    PackageInstallPlan,
    PackageKind,
    PackageLayer,
    PackageLock,
    PackagePromotion,
    PackageSet,
    PackageSetMember,
    PackageVariant,
)
from osfabricum.db.session import sync_session

KERNEL_BOUND_KINDS = ("kernel-module", "driver")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cache keys (the heart, G-28)
# ---------------------------------------------------------------------------


def compute_cache_key(
    *,
    name: str,
    version: str,
    arch: str,
    kind: str = "system",
    source_hash: str = "",
    recipe_hash: str = "",
    feature_hash: str = "",
    libc: str = "",
    toolchain_hash: str = "",
    abi_hash: str = "",
    kernel_release: str | None = None,
    kernel_config_hash: str | None = None,
) -> dict[str, Any]:
    """Compose a package cache key from its full identity (never name+ver+arch).

    Returns ``{"cache_key", "components"}``. Raises if a kernel-bound kind is
    missing its kernel binding.
    """
    if kind in KERNEL_BOUND_KINDS and (not kernel_release or not kernel_config_hash):
        raise ValueError(
            f"kernel-bound package (kind={kind!r}) requires kernel_release and "
            f"kernel_config_hash in its cache key"
        )
    components: dict[str, Any] = {
        "name": name,
        "version": version,
        "source_hash": source_hash,
        "recipe_hash": recipe_hash,
        "feature_hash": feature_hash,
        "arch": arch,
        "libc": libc,
        "toolchain_hash": toolchain_hash,
        "abi_hash": abi_hash,
        "kind": kind,
    }
    if kind in KERNEL_BOUND_KINDS:
        components["kernel_release"] = kernel_release
        components["kernel_config_hash"] = kernel_config_hash
    digest = _sha(json.dumps(components, sort_keys=True))
    return {"cache_key": f"pkgcache:{digest}", "components": components}


def explain_cache(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Explain how two key-component maps differ (the key-diff report)."""
    fields = sorted(set(a) | set(b))
    differs = [f for f in fields if a.get(f) != b.get(f)]
    return {
        "same": not differs,
        "differs": differs,
        "detail": {f: {"a": a.get(f), "b": b.get(f)} for f in differs},
    }


def record_cache_entry(
    *, artifact_id: str | None = None, db_url: str | None = None, **key_kwargs: Any
) -> dict[str, Any]:
    """Record (or find) a cache entry for the given key identity.

    Returns ``{cache_key, hit, id}`` where ``hit`` is True when an identical key
    already existed. Kernel-bound entries also get a ``package_compatibility``
    row recording what kernel/toolchain/ABI they are bound to.
    """
    result = compute_cache_key(**key_kwargs)
    key, components = result["cache_key"], result["components"]
    with sync_session(db_url) as s:
        existing = s.scalar(select(PackageCacheEntry).where(PackageCacheEntry.cache_key == key))
        if existing is not None:
            return {"cache_key": key, "hit": True, "id": existing.id}
        entry = PackageCacheEntry(
            cache_key=key,
            package_name=components["name"],
            version=components["version"],
            arch=components["arch"],
            kind=components["kind"],
            key_fields_json=components,
            artifact_id=artifact_id,
        )
        s.add(entry)
        s.flush()
        if components["kind"] in KERNEL_BOUND_KINDS:
            s.add(
                PackageCompatibility(
                    cache_entry_id=entry.id,
                    package_name=components["name"],
                    kind=components["kind"],
                    kernel_release=components.get("kernel_release"),
                    kernel_config_hash=components.get("kernel_config_hash"),
                    toolchain_hash=components.get("toolchain_hash"),
                    abi_hash=components.get("abi_hash"),
                )
            )
        s.commit()
        return {"cache_key": key, "hit": False, "id": entry.id}


def lookup_cache(*, db_url: str | None = None, **key_kwargs: Any) -> dict[str, Any]:
    """Look a key identity up in the cache, explaining a miss.

    On a hit returns the artifact. On a miss, finds the most recent entry for the
    same package name and reports which key component differs (so the rebuild
    reason is explicit).
    """
    result = compute_cache_key(**key_kwargs)
    key, components = result["cache_key"], result["components"]
    with sync_session(db_url) as s:
        entry = s.scalar(select(PackageCacheEntry).where(PackageCacheEntry.cache_key == key))
        if entry is not None:
            return {
                "cache_key": key,
                "hit": True,
                "artifact_id": entry.artifact_id,
                "components": components,
            }
        nearest = s.scalar(
            select(PackageCacheEntry)
            .where(PackageCacheEntry.package_name == components["name"])
            .order_by(PackageCacheEntry.created_at.desc())
        )
        out: dict[str, Any] = {"cache_key": key, "hit": False, "components": components}
        if nearest is not None:
            out["nearest_key"] = nearest.cache_key
            out["explain"] = explain_cache(nearest.key_fields_json, components)
        return out


def cache_stats(*, db_url: str | None = None) -> dict[str, Any]:
    """Cache entry counts overall and by kind."""
    with sync_session(db_url) as s:
        total = s.scalar(select(func.count()).select_from(PackageCacheEntry)) or 0
        by_kind: dict[str, int] = {
            kind: count
            for kind, count in s.execute(
                select(PackageCacheEntry.kind, func.count()).group_by(PackageCacheEntry.kind)
            ).all()
        }
        return {"total": total, "by_kind": by_kind}


# ---------------------------------------------------------------------------
# Taxonomy (kinds / layers)
# ---------------------------------------------------------------------------


def list_kinds(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {"name": k.name, "description": k.description}
            for k in s.scalars(select(PackageKind).order_by(PackageKind.name)).all()
        ]


def list_layers(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {"name": layer.name, "position": layer.position, "description": layer.description}
            for layer in s.scalars(select(PackageLayer).order_by(PackageLayer.position)).all()
        ]


def classify_package(
    package_id: str, *, kind: str, layer: str, db_url: str | None = None
) -> dict[str, Any]:
    """Assign a kind and layer to a package (validated against the taxonomy)."""
    with sync_session(db_url) as s:
        pkg = s.get(Package, package_id)
        if pkg is None:
            raise ValueError(f"package not found: {package_id!r}")
        if s.scalar(select(PackageKind).where(PackageKind.name == kind)) is None:
            raise ValueError(f"unknown package kind: {kind!r}")
        if s.scalar(select(PackageLayer).where(PackageLayer.name == layer)) is None:
            raise ValueError(f"unknown package layer: {layer!r}")
        pkg.kind = kind
        pkg.layer = layer
        s.commit()
        return {"id": pkg.id, "name": pkg.name, "kind": kind, "layer": layer}


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def create_group(
    name: str,
    *,
    distribution_id: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        dup = s.scalar(
            select(PackageGroup).where(
                PackageGroup.name == name, PackageGroup.distribution_id == distribution_id
            )
        )
        if dup is not None:
            raise ValueError(f"package group already exists: {name!r}")
        group = PackageGroup(name=name, distribution_id=distribution_id, description=description)
        s.add(group)
        s.commit()
        return {"id": group.id, "name": name}


def add_to_group(
    group_id: str,
    package_id: str,
    *,
    version_constraint: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.get(PackageGroup, group_id) is None:
            raise ValueError(f"package group not found: {group_id!r}")
        if s.get(Package, package_id) is None:
            raise ValueError(f"package not found: {package_id!r}")
        if s.get(PackageGroupMember, (group_id, package_id)) is None:
            s.add(
                PackageGroupMember(
                    group_id=group_id,
                    package_id=package_id,
                    version_constraint=version_constraint,
                )
            )
            s.commit()
        return {"group_id": group_id, "package_id": package_id}


def list_groups(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        out: list[dict[str, Any]] = []
        for g in s.scalars(select(PackageGroup).order_by(PackageGroup.name)).all():
            members = s.scalars(
                select(PackageGroupMember.package_id).where(PackageGroupMember.group_id == g.id)
            ).all()
            out.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "distribution_id": g.distribution_id,
                    "global": g.distribution_id is None,
                    "member_count": len(members),
                }
            )
        return out


# ---------------------------------------------------------------------------
# Sets + install-plan resolution
# ---------------------------------------------------------------------------


def create_set(
    name: str,
    *,
    distribution_id: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        dup = s.scalar(
            select(PackageSet).where(
                PackageSet.name == name, PackageSet.distribution_id == distribution_id
            )
        )
        if dup is not None:
            raise ValueError(f"package set already exists: {name!r}")
        pset = PackageSet(name=name, distribution_id=distribution_id, description=description)
        s.add(pset)
        s.commit()
        return {"id": pset.id, "name": name}


def add_to_set(
    set_id: str,
    *,
    member_kind: str,
    group_id: str | None = None,
    package_id: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    if member_kind not in ("group", "package"):
        raise ValueError("member_kind must be 'group' or 'package'")
    if member_kind == "group" and not group_id:
        raise ValueError("group member requires group_id")
    if member_kind == "package" and not package_id:
        raise ValueError("package member requires package_id")
    with sync_session(db_url) as s:
        if s.get(PackageSet, set_id) is None:
            raise ValueError(f"package set not found: {set_id!r}")
        s.add(
            PackageSetMember(
                set_id=set_id, member_kind=member_kind, group_id=group_id, package_id=package_id
            )
        )
        s.commit()
        return {"set_id": set_id, "member_kind": member_kind}


def list_sets(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "id": ps.id,
                "name": ps.name,
                "distribution_id": ps.distribution_id,
                "description": ps.description,
            }
            for ps in s.scalars(select(PackageSet).order_by(PackageSet.name)).all()
        ]


def resolve_set(
    set_id: str, *, profile_id: str | None = None, db_url: str | None = None
) -> dict[str, Any]:
    """Expand a set into a deterministic, layer-ordered install plan and record it.

    Packages are gathered from the set's direct package members and from every
    group it references, deduplicated, then ordered by layer position (lowest
    first) and name. The plan is stored as a :class:`PackageInstallPlan` with a
    content hash (the ``install-plan`` artifact record).
    """
    with sync_session(db_url) as s:
        if s.get(PackageSet, set_id) is None:
            raise ValueError(f"package set not found: {set_id!r}")
        layer_pos = {layer.name: layer.position for layer in s.scalars(select(PackageLayer)).all()}
        members = s.scalars(select(PackageSetMember).where(PackageSetMember.set_id == set_id)).all()

        package_ids: set[str] = set()
        for m in members:
            if m.member_kind == "package" and m.package_id:
                package_ids.add(m.package_id)
            elif m.member_kind == "group" and m.group_id:
                for pid in s.scalars(
                    select(PackageGroupMember.package_id).where(
                        PackageGroupMember.group_id == m.group_id
                    )
                ).all():
                    package_ids.add(pid)

        entries: list[dict[str, Any]] = []
        for pid in package_ids:
            pkg = s.get(Package, pid)
            if pkg is None:
                continue
            layer = pkg.layer or "system"
            entries.append(
                {
                    "package": pkg.name,
                    "package_id": pkg.id,
                    "kind": pkg.kind or "system",
                    "layer": layer,
                    "position": layer_pos.get(layer, 99),
                }
            )
        entries.sort(key=lambda e: (e["position"], e["package"]))

        plan = {"set_id": set_id, "profile_id": profile_id, "packages": entries}
        plan_hash = "sha256:" + _sha(json.dumps(plan, sort_keys=True))
        record = PackageInstallPlan(
            set_id=set_id, profile_id=profile_id, plan_json=plan, plan_hash=plan_hash
        )
        s.add(record)
        s.commit()
        return {
            "id": record.id,
            "set_id": set_id,
            "profile_id": profile_id,
            "packages": entries,
            "plan_hash": plan_hash,
        }


# ---------------------------------------------------------------------------
# Locks / feeds / promotions / variants
# ---------------------------------------------------------------------------


def create_lock(
    package_name: str,
    version: str,
    *,
    cache_key: str | None = None,
    reason: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        dup = s.scalar(
            select(PackageLock).where(
                PackageLock.package_name == package_name, PackageLock.version == version
            )
        )
        if dup is not None:
            raise ValueError(f"lock already exists: {package_name}@{version}")
        lock = PackageLock(
            package_name=package_name, version=version, cache_key=cache_key, reason=reason
        )
        s.add(lock)
        s.commit()
        return {"id": lock.id, "package_name": package_name, "version": version}


def list_locks(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "id": locked.id,
                "package_name": locked.package_name,
                "version": locked.version,
                "cache_key": locked.cache_key,
                "reason": locked.reason,
            }
            for locked in s.scalars(select(PackageLock).order_by(PackageLock.package_name)).all()
        ]


def create_feed(
    name: str,
    *,
    channel: str = "stable",
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.scalar(select(PackageFeed).where(PackageFeed.name == name)) is not None:
            raise ValueError(f"feed already exists: {name!r}")
        feed = PackageFeed(name=name, channel=channel, description=description)
        s.add(feed)
        s.commit()
        return {"id": feed.id, "name": name, "channel": channel}


def add_feed_index(
    feed_id: str,
    package_name: str,
    version: str,
    *,
    cache_key: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.get(PackageFeed, feed_id) is None:
            raise ValueError(f"feed not found: {feed_id!r}")
        existing = s.scalars(
            select(PackageFeedIndex.position).where(PackageFeedIndex.feed_id == feed_id)
        ).all()
        position = (max(existing) + 1) if existing else 0
        entry = PackageFeedIndex(
            feed_id=feed_id,
            package_name=package_name,
            version=version,
            cache_key=cache_key,
            position=position,
        )
        s.add(entry)
        s.commit()
        return {"id": entry.id, "feed_id": feed_id, "package_name": package_name}


def list_feeds(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {"id": f.id, "name": f.name, "channel": f.channel, "description": f.description}
            for f in s.scalars(select(PackageFeed).order_by(PackageFeed.name)).all()
        ]


def promote(
    package_name: str,
    version: str,
    to_channel: str,
    *,
    from_channel: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        promotion = PackagePromotion(
            package_name=package_name,
            version=version,
            from_channel=from_channel,
            to_channel=to_channel,
        )
        s.add(promotion)
        s.commit()
        return {
            "id": promotion.id,
            "package_name": package_name,
            "version": version,
            "to_channel": to_channel,
        }


def create_variant(
    package_id: str,
    name: str,
    *,
    feature_hash: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.get(Package, package_id) is None:
            raise ValueError(f"package not found: {package_id!r}")
        variant = PackageVariant(
            package_id=package_id, name=name, feature_hash=feature_hash, description=description
        )
        s.add(variant)
        s.commit()
        return {"id": variant.id, "package_id": package_id, "name": name}


def list_variants(package_id: str, *, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {"id": v.id, "name": v.name, "feature_hash": v.feature_hash}
            for v in s.scalars(
                select(PackageVariant).where(PackageVariant.package_id == package_id)
            ).all()
        ]
