"""Package Feature / Variant Manager (M36).

Declares a package's build options (ssl backend, dbus, static/dynamic, init
backend, busybox applets, cargo/cmake/meson flags, …) and resolves a requested
feature set into a concrete variant. The heart is :func:`resolve_variant`: it
validates requested values against the declared option schema, fills defaults,
collects the package dependencies those feature values pull in, and computes a
deterministic ``feature_hash``.

That ``feature_hash`` is exactly the ``feature_hash`` component of the M35
package cache key — so changing a feature value changes the variant hash, which
changes the cache key, which forces a rebuild (and the feature diff is visible).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osfabricum.db.models import (
    Package,
    PackageBuildVariant,
    PackageFeatureOption,
    PackageFeatureValue,
    PackageVariantArtifact,
)
from osfabricum.db.session import sync_session

FEATURE_TYPES = ("bool", "choice", "string", "int")
_BOOL_VALUES = ("y", "n")


def _feature_hash(resolved: dict[str, str]) -> str:
    return (
        "sha256:" + hashlib.sha256(json.dumps(resolved, sort_keys=True).encode("utf-8")).hexdigest()
    )


def _type_ok(opt_type: str, value: str, allowed: set[str]) -> bool:
    if opt_type == "bool":
        return value in _BOOL_VALUES
    if opt_type == "choice":
        return value in allowed
    if opt_type == "int":
        return value.lstrip("-").isdigit()
    return True  # string


def _package_or_raise(s: Session, package_id: str) -> Package:
    pkg = s.get(Package, package_id)
    if pkg is None:
        raise ValueError(f"package not found: {package_id!r}")
    return pkg


def define_feature(
    package_id: str,
    name: str,
    feature_type: str,
    *,
    default: str | None = None,
    values: list[dict[str, Any]] | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Declare a feature option (and its allowed values) on a package.

    *values* items: ``{value, implied_deps?[], description?}``. ``choice`` options
    require values; ``bool`` options may declare ``y``/``n`` value rows to attach
    implied dependencies.
    """
    if feature_type not in FEATURE_TYPES:
        raise ValueError(
            f"unknown feature type: {feature_type!r} (known: {', '.join(FEATURE_TYPES)})"
        )
    if feature_type == "choice" and not values:
        raise ValueError("choice feature requires at least one value")
    with sync_session(db_url) as s:
        _package_or_raise(s, package_id)
        if (
            s.scalar(
                select(PackageFeatureOption).where(
                    PackageFeatureOption.package_id == package_id,
                    PackageFeatureOption.name == name,
                )
            )
            is not None
        ):
            raise ValueError(f"feature already defined: {name!r}")
        option = PackageFeatureOption(
            package_id=package_id,
            name=name,
            type=feature_type,
            default_value=default,
            description=description,
        )
        s.add(option)
        s.flush()
        for v in values or []:
            s.add(
                PackageFeatureValue(
                    option_id=option.id,
                    value=v["value"],
                    implied_deps_json=v.get("implied_deps"),
                    description=v.get("description"),
                )
            )
        s.commit()
        return {"id": option.id, "package_id": package_id, "name": name, "type": feature_type}


def list_features(package_id: str, *, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        _package_or_raise(s, package_id)
        options = s.scalars(
            select(PackageFeatureOption)
            .where(PackageFeatureOption.package_id == package_id)
            .order_by(PackageFeatureOption.name)
        ).all()
        out: list[dict[str, Any]] = []
        for opt in options:
            vals = s.scalars(
                select(PackageFeatureValue).where(PackageFeatureValue.option_id == opt.id)
            ).all()
            out.append(
                {
                    "name": opt.name,
                    "type": opt.type,
                    "default": opt.default_value,
                    "description": opt.description,
                    "values": [
                        {"value": v.value, "implied_deps": v.implied_deps_json or []} for v in vals
                    ],
                }
            )
        return out


def resolve_variant(
    package_id: str, requested: dict[str, str], *, db_url: str | None = None
) -> dict[str, Any]:
    """Resolve a requested feature set into a variant (the heart).

    Validates each requested value against the option's type/choices, fills
    defaults for unspecified options, collects feature-dependent package deps,
    and computes a deterministic ``feature_hash`` (the M35 cache-key component).
    """
    with sync_session(db_url) as s:
        _package_or_raise(s, package_id)
        options = {
            opt.name: opt
            for opt in s.scalars(
                select(PackageFeatureOption).where(PackageFeatureOption.package_id == package_id)
            ).all()
        }
        values_by_option: dict[str, list[PackageFeatureValue]] = {}
        for opt in options.values():
            values_by_option[opt.name] = list(
                s.scalars(
                    select(PackageFeatureValue).where(PackageFeatureValue.option_id == opt.id)
                ).all()
            )

    errors: list[str] = []
    resolved: dict[str, str] = {}
    deps: set[str] = set()

    for name in requested:
        if name not in options:
            errors.append(f"unknown feature: {name}")

    for name, opt in options.items():
        allowed = {v.value for v in values_by_option[name]}
        if name in requested:
            value = requested[name]
        elif opt.default_value is not None:
            value = opt.default_value
        else:
            errors.append(f"feature {name} has no value and no default")
            continue
        if not _type_ok(opt.type, value, allowed):
            kind = "choices: " + ", ".join(sorted(allowed)) if opt.type == "choice" else opt.type
            errors.append(f"invalid value {value!r} for {name} ({kind})")
            continue
        resolved[name] = value
        for v in values_by_option[name]:
            if v.value == value and v.implied_deps_json:
                deps.update(v.implied_deps_json)

    feature_hash = _feature_hash(dict(sorted(resolved.items())))
    return {
        "package_id": package_id,
        "resolved": resolved,
        "feature_hash": feature_hash,
        "deps": sorted(deps),
        "errors": errors,
        "valid": not errors,
    }


def diff_variants(a: dict[str, str], b: dict[str, str]) -> dict[str, Any]:
    """Diff two resolved feature maps (the feature diff in a build diff)."""
    fields = sorted(set(a) | set(b))
    differs = [f for f in fields if a.get(f) != b.get(f)]
    return {
        "same": not differs,
        "differs": differs,
        "detail": {f: {"a": a.get(f), "b": b.get(f)} for f in differs},
    }


def record_build_variant(
    package_id: str,
    name: str,
    requested: dict[str, str],
    *,
    arch: str | None = None,
    description: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Resolve and persist a build variant (idempotent on feature_hash + arch)."""
    result = resolve_variant(package_id, requested, db_url=db_url)
    if not result["valid"]:
        raise ValueError("; ".join(result["errors"]))
    feature_hash = result["feature_hash"]
    with sync_session(db_url) as s:
        existing = s.scalar(
            select(PackageBuildVariant).where(
                PackageBuildVariant.package_id == package_id,
                PackageBuildVariant.feature_hash == feature_hash,
                PackageBuildVariant.arch == arch,
            )
        )
        if existing is not None:
            return {"id": existing.id, "feature_hash": feature_hash, "hit": True}
        variant = PackageBuildVariant(
            package_id=package_id,
            name=name,
            feature_hash=feature_hash,
            arch=arch,
            resolved_json=result["resolved"],
            description=description,
        )
        s.add(variant)
        s.commit()
        return {"id": variant.id, "feature_hash": feature_hash, "hit": False}


def list_build_variants(package_id: str, *, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "id": v.id,
                "name": v.name,
                "feature_hash": v.feature_hash,
                "arch": v.arch,
                "resolved": v.resolved_json,
            }
            for v in s.scalars(
                select(PackageBuildVariant).where(PackageBuildVariant.package_id == package_id)
            ).all()
        ]


def add_variant_artifact(
    build_variant_id: str,
    *,
    artifact_id: str | None = None,
    arch: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.get(PackageBuildVariant, build_variant_id) is None:
            raise ValueError(f"build variant not found: {build_variant_id!r}")
        art = PackageVariantArtifact(
            build_variant_id=build_variant_id, artifact_id=artifact_id, arch=arch
        )
        s.add(art)
        s.commit()
        return {"id": art.id, "build_variant_id": build_variant_id}
