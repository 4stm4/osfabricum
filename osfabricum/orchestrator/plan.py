"""Plan resolution with name-based overrides (M29).

``POST /v1/plan`` resolves a build plan for a (distribution, profile, board)
triple, optionally applying overrides given **by name** (package_set / kernel /
toolchain) plus ``packages`` and ``inputs``. Names are resolved to ids and
handed to the resolver as id-based overrides. No build is started here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from osfabricum.db.models import Distribution, Kernel, PackageSet, Toolchain
from osfabricum.db.session import sync_session
from osfabricum.resolver import resolve_plan


def resolve_override_ids(
    overrides: dict[str, Any] | None, distribution: str, db_url: str | None
) -> dict[str, Any]:
    """Translate name-based overrides into the id-based form the resolver wants."""
    result: dict[str, Any] = {}
    if not overrides:
        return result
    with sync_session(db_url) as s:
        dist = s.scalar(select(Distribution).where(Distribution.name == distribution))
        dist_id = dist.id if dist is not None else None

        if overrides.get("package_set"):
            name = overrides["package_set"]
            pset = s.scalar(
                select(PackageSet).where(
                    PackageSet.name == name,
                    or_(
                        PackageSet.distribution_id == dist_id, PackageSet.distribution_id.is_(None)
                    ),
                )
            )
            if pset is None:
                raise ValueError(f"unknown package_set: {name!r}")
            result["package_set_id"] = pset.id

        if overrides.get("kernel"):
            name = overrides["kernel"]
            kernel = s.scalar(select(Kernel).where(Kernel.name == name))
            if kernel is None:
                raise ValueError(f"unknown kernel: {name!r}")
            result["kernel_id"] = kernel.id

        if overrides.get("toolchain"):
            name = overrides["toolchain"]
            tc = s.scalar(select(Toolchain).where(Toolchain.name == name))
            if tc is None:
                raise ValueError(f"unknown toolchain: {name!r}")
            result["toolchain_id"] = tc.id

    if isinstance(overrides.get("packages"), list):
        result["packages"] = overrides["packages"]
    if isinstance(overrides.get("inputs"), dict):
        result["inputs"] = overrides["inputs"]
    return result


def resolve_plan_request(
    *,
    distribution: str,
    profile: str,
    board: str,
    overrides: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Resolve a plan (with name-based overrides) and return it as a dict."""
    id_overrides = resolve_override_ids(overrides, distribution, db_url)
    plan = resolve_plan(distribution, profile, board, db_url=db_url, overrides=id_overrides)
    return plan.to_dict()


def validate_plan(
    *,
    distribution: str,
    profile: str,
    board: str,
    overrides: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Resolve a plan and report validity + what is missing (never builds)."""
    try:
        plan = resolve_plan_request(
            distribution=distribution,
            profile=profile,
            board=board,
            overrides=overrides,
            db_url=db_url,
        )
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)], "missing_artifacts": [], "required_jobs": []}
    return {
        "valid": True,
        "errors": [],
        "missing_artifacts": plan["missing_artifacts"],
        "required_jobs": plan["required_jobs"],
        "resolution_hash": plan["resolution_hash"],
    }


def _package_keys(plan: dict[str, Any]) -> set[str]:
    return {f"{p['name']}:{p['version']}" for p in plan["packages"]}


def _ref_name(value: dict[str, Any] | None) -> str | None:
    return value.get("name") if value else None


def diff_plans(
    *,
    distribution: str,
    board: str,
    a: dict[str, Any],
    b: dict[str, Any],
    db_url: str | None = None,
) -> dict[str, Any]:
    """Diff two plans (each ``{profile, overrides?}``) sharing distribution+board."""
    plan_a = resolve_plan_request(
        distribution=distribution,
        profile=a["profile"],
        board=board,
        overrides=a.get("overrides"),
        db_url=db_url,
    )
    plan_b = resolve_plan_request(
        distribution=distribution,
        profile=b["profile"],
        board=board,
        overrides=b.get("overrides"),
        db_url=db_url,
    )
    keys_a, keys_b = _package_keys(plan_a), _package_keys(plan_b)
    return {
        "a": {"profile": a["profile"], "resolution_hash": plan_a["resolution_hash"]},
        "b": {"profile": b["profile"], "resolution_hash": plan_b["resolution_hash"]},
        "packages_added": sorted(keys_b - keys_a),
        "packages_removed": sorted(keys_a - keys_b),
        "kernel": {"a": _ref_name(plan_a["kernel"]), "b": _ref_name(plan_b["kernel"])},
        "toolchain": {"a": _ref_name(plan_a["toolchain"]), "b": _ref_name(plan_b["toolchain"])},
        "identical": plan_a["resolution_hash"] == plan_b["resolution_hash"],
    }
