"""Profile write service (M27).

Profiles select the universal entities by name; this layer resolves those names
to ids, persists the profile, and supports clone / version / diff / import /
export. The resolver (``osfabricum.resolver``) consumes the persisted selections
(package_set, toolchain, kernel, inputs) — see G-02.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osfabricum.db.models import (
    Board,
    BootScheme,
    BrandingProfile,
    Distribution,
    DistributionClass,
    GraphicalProfile,
    ImageRecipe,
    Kernel,
    NetworkProfile,
    PackageSet,
    Profile,
    ProfileVersion,
    SecurityProfile,
    Toolchain,
    UpdateStrategy,
    ValidationProfile,
)
from osfabricum.db.session import sync_session
from osfabricum.profile.schema import API_VERSION, KIND, REF_FIELDS, validate_doc

# field -> (Model, dist_scoped). dist_scoped entities resolve within the
# distribution first, then fall back to a global (distribution_id NULL) one.
_REF_MODELS: dict[str, tuple[Any, bool]] = {
    "class": (DistributionClass, False),
    "board": (Board, False),
    "kernel": (Kernel, False),
    "toolchain": (Toolchain, False),
    "boot_scheme": (BootScheme, False),
    "package_set": (PackageSet, True),
    "image_recipe": (ImageRecipe, True),
    "branding_profile": (BrandingProfile, True),
    "graphical_profile": (GraphicalProfile, True),
    "network_profile": (NetworkProfile, True),
    "security_profile": (SecurityProfile, True),
    "update_strategy": (UpdateStrategy, True),
    "validation_profile": (ValidationProfile, True),
}


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------


def _ref_id(session: Session, field: str, name: str, distribution_id: str) -> str:
    model, dist_scoped = _REF_MODELS[field]
    obj = None
    if dist_scoped:
        obj = session.scalar(
            select(model).where(model.name == name, model.distribution_id == distribution_id)
        )
        if obj is None:
            obj = session.scalar(
                select(model).where(model.name == name, model.distribution_id.is_(None))
            )
    else:
        obj = session.scalar(select(model).where(model.name == name))
    if obj is None:
        raise ValueError(f"unknown {field}: {name!r}")
    return str(obj.id)


def _ref_name(session: Session, field: str, id_value: str | None) -> str | None:
    if not id_value:
        return None
    model, _ = _REF_MODELS[field]
    obj = session.get(model, id_value)
    return str(obj.name) if obj is not None else None


def _resolve_ref_columns(
    session: Session, distribution_id: str, refs: dict[str, Any]
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for field, name in refs.items():
        if field not in REF_FIELDS:
            raise ValueError(f"unknown profile field: {field!r}")
        out[REF_FIELDS[field]] = _ref_id(session, field, name, distribution_id) if name else None
    return out


def _find_distribution(session: Session, name: str) -> Distribution:
    dist = session.get(Distribution, name)
    if dist is None:
        dist = session.scalar(select(Distribution).where(Distribution.name == name))
    if dist is None:
        raise ValueError(f"distribution not found: {name!r}")
    return dist


def _find_profile(session: Session, distribution: str, name: str) -> Profile:
    dist = _find_distribution(session, distribution)
    prof = session.scalar(
        select(Profile).where(Profile.distribution_id == dist.id, Profile.name == name)
    )
    if prof is None:
        raise ValueError(f"profile not found: {distribution}/{name}")
    return prof


def _to_dict(session: Session, profile: Profile) -> dict[str, Any]:
    dist = session.get(Distribution, profile.distribution_id)
    inherits_name: str | None = None
    if profile.inherits_id:
        parent = session.get(Profile, profile.inherits_id)
        inherits_name = parent.name if parent is not None else None
    data: dict[str, Any] = {
        "id": profile.id,
        "distribution": dist.name if dist is not None else None,
        "name": profile.name,
        "inherits": inherits_name,
        "inputs": profile.inputs_json or {},
    }
    for field, column in REF_FIELDS.items():
        data[field] = _ref_name(session, field, getattr(profile, column))
    return data


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_profile(
    *,
    distribution: str,
    name: str,
    inherits: str | None = None,
    refs: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    refs = refs or {}
    with sync_session(db_url) as s:
        dist = _find_distribution(s, distribution)
        if (
            s.scalar(
                select(Profile).where(Profile.distribution_id == dist.id, Profile.name == name)
            )
            is not None
        ):
            raise ValueError(f"profile already exists: {distribution}/{name}")
        columns = _resolve_ref_columns(s, dist.id, refs)
        inherits_id = None
        if inherits:
            inherits_id = _find_profile(s, distribution, inherits).id
        prof = Profile(
            distribution_id=dist.id,
            name=name,
            inherits_id=inherits_id,
            inputs_json=inputs,
            **columns,
        )
        s.add(prof)
        s.flush()
        result = _to_dict(s, prof)
        s.commit()
        return result


def get_profile(distribution: str, name: str, *, db_url: str | None = None) -> dict[str, Any]:
    with sync_session(db_url) as s:
        return _to_dict(s, _find_profile(s, distribution, name))


def list_profiles(distribution: str, *, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        dist = _find_distribution(s, distribution)
        profiles = s.scalars(
            select(Profile).where(Profile.distribution_id == dist.id).order_by(Profile.name)
        ).all()
        return [_to_dict(s, p) for p in profiles]


def update_profile(
    distribution: str,
    name: str,
    *,
    inherits: Any = ...,
    refs: dict[str, Any] | None = None,
    inputs: Any = ...,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        prof = _find_profile(s, distribution, name)
        if refs:
            for column, value in _resolve_ref_columns(s, prof.distribution_id, refs).items():
                setattr(prof, column, value)
        if inherits is not ...:
            prof.inherits_id = _find_profile(s, distribution, inherits).id if inherits else None
        if inputs is not ...:
            prof.inputs_json = inputs
        s.flush()
        result = _to_dict(s, prof)
        s.commit()
        return result


def delete_profile(distribution: str, name: str, *, db_url: str | None = None) -> None:
    with sync_session(db_url) as s:
        prof = _find_profile(s, distribution, name)
        children = s.scalars(select(Profile).where(Profile.inherits_id == prof.id)).all()
        if children:
            names = ", ".join(c.name for c in children)
            raise ValueError(f"profile {name!r} is inherited by: {names}; refusing to delete")
        for ver in s.scalars(
            select(ProfileVersion).where(ProfileVersion.profile_id == prof.id)
        ).all():
            s.delete(ver)
        s.delete(prof)
        s.commit()


# ---------------------------------------------------------------------------
# Clone / version / diff / import / export
# ---------------------------------------------------------------------------

_CLONE_SKIP = {"id", "name"}


def clone_profile(
    distribution: str, name: str, new_name: str, *, db_url: str | None = None
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        src = _find_profile(s, distribution, name)
        if (
            s.scalar(
                select(Profile).where(
                    Profile.distribution_id == src.distribution_id, Profile.name == new_name
                )
            )
            is not None
        ):
            raise ValueError(f"profile already exists: {distribution}/{new_name}")
        values = {
            c.name: getattr(src, c.name)
            for c in Profile.__table__.columns
            if c.name not in _CLONE_SKIP
        }
        clone = Profile(**{**values, "name": new_name})
        s.add(clone)
        s.flush()
        result = _to_dict(s, clone)
        s.commit()
        return result


def create_version(distribution: str, name: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Snapshot the current profile state as the next immutable version."""
    with sync_session(db_url) as s:
        prof = _find_profile(s, distribution, name)
        latest = s.scalar(
            select(ProfileVersion.version)
            .where(ProfileVersion.profile_id == prof.id)
            .order_by(ProfileVersion.version.desc())
        )
        version = (latest or 0) + 1
        snapshot = _to_dict(s, prof)
        s.add(ProfileVersion(profile_id=prof.id, version=version, snapshot_json=snapshot))
        s.commit()
        return {"profile": f"{distribution}/{name}", "version": version, "snapshot": snapshot}


def list_versions(
    distribution: str, name: str, *, db_url: str | None = None
) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        prof = _find_profile(s, distribution, name)
        rows = s.scalars(
            select(ProfileVersion)
            .where(ProfileVersion.profile_id == prof.id)
            .order_by(ProfileVersion.version)
        ).all()
        return [
            {
                "version": r.version,
                "created_at": r.created_at.isoformat(),
                "snapshot": r.snapshot_json,
            }
            for r in rows
        ]


def diff_profiles(
    distribution: str, name_a: str, name_b: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Field-level diff of two profiles in the same distribution."""
    with sync_session(db_url) as s:
        a = _to_dict(s, _find_profile(s, distribution, name_a))
        b = _to_dict(s, _find_profile(s, distribution, name_b))
    fields = ["inherits", "inputs", *REF_FIELDS.keys()]
    changes = {f: {"a": a.get(f), "b": b.get(f)} for f in fields if a.get(f) != b.get(f)}
    return {"distribution": distribution, "a": name_a, "b": name_b, "changes": changes}


def export_profile(distribution: str, name: str, *, db_url: str | None = None) -> dict[str, Any]:
    with sync_session(db_url) as s:
        data = _to_dict(s, _find_profile(s, distribution, name))
    spec: dict[str, Any] = {"inherits": data["inherits"], "inputs": data["inputs"]}
    for field in REF_FIELDS:
        spec[field] = data[field]
    return {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "metadata": {"distribution": data["distribution"], "name": data["name"]},
        "spec": spec,
    }


def import_profile(
    data: Any, *, db_url: str | None = None, overwrite: bool = False
) -> dict[str, Any]:
    errors = validate_doc(data)
    if errors:
        raise ValueError("invalid profile document: " + "; ".join(errors))
    meta = data["metadata"]
    spec = data.get("spec", {})
    distribution = meta["distribution"]
    name = meta["name"]
    refs = {f: spec[f] for f in REF_FIELDS if f in spec}

    with sync_session(db_url) as s:
        dist = _find_distribution(s, distribution)
        existing = s.scalar(
            select(Profile).where(Profile.distribution_id == dist.id, Profile.name == name)
        )
        if existing is not None:
            if not overwrite:
                raise ValueError(
                    f"profile already exists: {distribution}/{name} (pass overwrite=True)"
                )
            s.delete(existing)
            s.flush()
        columns = _resolve_ref_columns(s, dist.id, refs)
        inherits_id = None
        if spec.get("inherits"):
            inherits_id = _find_profile(s, distribution, spec["inherits"]).id
        prof = Profile(
            distribution_id=dist.id,
            name=name,
            inherits_id=inherits_id,
            inputs_json=spec.get("inputs"),
            **columns,
        )
        s.add(prof)
        s.flush()
        result = _to_dict(s, prof)
        s.commit()
        return result
