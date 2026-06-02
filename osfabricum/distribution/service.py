"""Distribution write service (M26).

All distribution create/update/delete/clone/import/export logic lives here and
operates directly on the database via :func:`sync_session`. Functions return
plain ``dict`` structures so the API and CLI can serialize them uniformly.
Domain errors are raised as :class:`ValueError`; callers map them to HTTP 400/
404 or CLI exit codes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osfabricum.db.models import Build, Distribution, DistributionClass, Profile
from osfabricum.db.session import sync_session
from osfabricum.distribution.schema import API_VERSION, KIND, validate_doc

# Profile columns copied verbatim on clone (everything except identity/linkage
# that must be remapped). Generic so new M25+ columns are cloned automatically.
_CLONE_SKIP = {"id", "distribution_id", "inherits_id"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _class_name_to_id(session: Session, class_name: str | None) -> str | None:
    if not class_name:
        return None
    cls = session.scalar(select(DistributionClass).where(DistributionClass.name == class_name))
    if cls is None:
        raise ValueError(f"unknown distribution class: {class_name!r}")
    return cls.id


def _find(session: Session, id_or_name: str) -> Distribution:
    dist = session.get(Distribution, id_or_name)
    if dist is None:
        dist = session.scalar(select(Distribution).where(Distribution.name == id_or_name))
    if dist is None:
        raise ValueError(f"distribution not found: {id_or_name!r}")
    return dist


def _class_map(session: Session) -> dict[str, str]:
    return {c.id: c.name for c in session.scalars(select(DistributionClass)).all()}


def _to_dict(session: Session, dist: Distribution) -> dict[str, Any]:
    classes = _class_map(session)
    profiles = session.scalars(
        select(Profile).where(Profile.distribution_id == dist.id).order_by(Profile.name)
    ).all()
    pid_to_name = {p.id: p.name for p in profiles}
    return {
        "id": dist.id,
        "name": dist.name,
        "description": dist.description,
        "default_channel": dist.default_channel,
        "class": classes.get(dist.class_id) if dist.class_id else None,
        "metadata": dist.metadata_json,
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "inherits": pid_to_name.get(p.inherits_id) if p.inherits_id else None,
                "class": classes.get(p.class_id) if p.class_id else None,
                "inputs": p.inputs_json or {},
            }
            for p in profiles
        ],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_distribution(
    *,
    name: str,
    description: str | None = None,
    default_channel: str = "dev",
    class_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.scalar(select(Distribution).where(Distribution.name == name)) is not None:
            raise ValueError(f"distribution already exists: {name!r}")
        dist = Distribution(
            name=name,
            description=description,
            default_channel=default_channel,
            class_id=_class_name_to_id(s, class_name),
            metadata_json=metadata,
        )
        s.add(dist)
        s.flush()
        result = _to_dict(s, dist)
        s.commit()
        return result


def get_distribution(id_or_name: str, *, db_url: str | None = None) -> dict[str, Any]:
    with sync_session(db_url) as s:
        return _to_dict(s, _find(s, id_or_name))


def list_distributions(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        classes = _class_map(s)
        count_rows = s.execute(
            select(Profile.distribution_id, func.count()).group_by(Profile.distribution_id)
        ).all()
        counts: dict[str, int] = {row[0]: int(row[1]) for row in count_rows}
        rows = s.scalars(select(Distribution).order_by(Distribution.name)).all()
        return [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "default_channel": d.default_channel,
                "class": classes.get(d.class_id) if d.class_id else None,
                "profile_count": int(counts.get(d.id, 0)),
            }
            for d in rows
        ]


_UNSET = object()


def update_distribution(
    id_or_name: str,
    *,
    description: Any = _UNSET,
    default_channel: Any = _UNSET,
    class_name: Any = _UNSET,
    metadata: Any = _UNSET,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        dist = _find(s, id_or_name)
        if description is not _UNSET:
            dist.description = description
        if default_channel is not _UNSET:
            dist.default_channel = default_channel
        if class_name is not _UNSET:
            dist.class_id = _class_name_to_id(s, class_name)
        if metadata is not _UNSET:
            dist.metadata_json = metadata
        s.flush()
        result = _to_dict(s, dist)
        s.commit()
        return result


def delete_distribution(id_or_name: str, *, db_url: str | None = None) -> None:
    with sync_session(db_url) as s:
        dist = _find(s, id_or_name)
        builds = s.scalar(
            select(func.count()).select_from(Build).where(Build.distribution_id == dist.id)
        )
        if builds:
            raise ValueError(
                f"distribution {dist.name!r} has {builds} build(s); refusing to delete"
            )
        for prof in s.scalars(select(Profile).where(Profile.distribution_id == dist.id)).all():
            s.delete(prof)
        s.delete(dist)
        s.commit()


# ---------------------------------------------------------------------------
# Clone / import / export
# ---------------------------------------------------------------------------


def clone_distribution(
    id_or_name: str, new_name: str, *, db_url: str | None = None
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        src = _find(s, id_or_name)
        if s.scalar(select(Distribution).where(Distribution.name == new_name)) is not None:
            raise ValueError(f"distribution already exists: {new_name!r}")
        clone = Distribution(
            name=new_name,
            description=src.description,
            default_channel=src.default_channel,
            class_id=src.class_id,
            metadata_json=src.metadata_json,
        )
        s.add(clone)
        s.flush()

        src_profiles = s.scalars(select(Profile).where(Profile.distribution_id == src.id)).all()
        id_map: dict[str, str] = {}
        for p in src_profiles:
            values = {
                c.name: getattr(p, c.name)
                for c in Profile.__table__.columns
                if c.name not in _CLONE_SKIP
            }
            np = Profile(distribution_id=clone.id, **values)
            s.add(np)
            s.flush()
            id_map[p.id] = np.id
        # Remap intra-distribution inheritance to the cloned profiles.
        for p in src_profiles:
            if p.inherits_id and p.inherits_id in id_map:
                clone_prof = s.get(Profile, id_map[p.id])
                if clone_prof is not None:
                    clone_prof.inherits_id = id_map[p.inherits_id]
        s.flush()
        result = _to_dict(s, clone)
        s.commit()
        return result


def export_distribution(id_or_name: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Serialize a distribution + its profiles to the portable document form."""
    with sync_session(db_url) as s:
        data = _to_dict(s, _find(s, id_or_name))
    return {
        "apiVersion": API_VERSION,
        "kind": KIND,
        "metadata": {
            "name": data["name"],
            "description": data["description"],
            "default_channel": data["default_channel"],
            "class": data["class"],
        },
        "profiles": [
            {
                "name": p["name"],
                "inherits": p["inherits"],
                "class": p["class"],
                "inputs": p["inputs"],
            }
            for p in data["profiles"]
        ],
    }


def import_distribution(
    data: Any, *, db_url: str | None = None, overwrite: bool = False
) -> dict[str, Any]:
    """Create a distribution (+ profiles) from a validated document."""
    errors = validate_doc(data)
    if errors:
        raise ValueError("invalid distribution document: " + "; ".join(errors))

    meta = data["metadata"]
    name = meta["name"]
    profiles_in = data.get("profiles", [])

    with sync_session(db_url) as s:
        existing = s.scalar(select(Distribution).where(Distribution.name == name))
        if existing is not None:
            if not overwrite:
                raise ValueError(f"distribution already exists: {name!r} (pass overwrite=True)")
            for prof in s.scalars(
                select(Profile).where(Profile.distribution_id == existing.id)
            ).all():
                s.delete(prof)
            s.delete(existing)
            s.flush()

        dist = Distribution(
            name=name,
            description=meta.get("description"),
            default_channel=meta.get("default_channel", "dev"),
            class_id=_class_name_to_id(s, meta.get("class")),
            metadata_json=meta.get("metadata"),
        )
        s.add(dist)
        s.flush()

        name_to_id: dict[str, str] = {}
        for prof in profiles_in:
            obj = Profile(
                distribution_id=dist.id,
                name=prof["name"],
                inputs_json=prof.get("inputs"),
                class_id=_class_name_to_id(s, prof.get("class")),
            )
            s.add(obj)
            s.flush()
            name_to_id[prof["name"]] = obj.id

        for prof in profiles_in:
            parent = prof.get("inherits")
            if not parent:
                continue
            if parent not in name_to_id:
                raise ValueError(f"profile {prof['name']!r} inherits unknown profile {parent!r}")
            child = s.get(Profile, name_to_id[prof["name"]])
            if child is not None:
                child.inherits_id = name_to_id[parent]

        s.flush()
        result = _to_dict(s, dist)
        s.commit()
        return result
