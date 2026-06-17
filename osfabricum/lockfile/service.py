"""Business logic for M62 — Manifest / Lockfile System."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import Lockfile, LockfileEntry, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_ENTRY_KINDS: frozenset[str] = frozenset(
    {"package", "kernel", "toolchain", "config", "layer", "source", "artifact", "build-env"}
)


def create_lockfile(
    session: "Session",
    distribution_id: str | None = None,
    profile_id: str | None = None,
    build_id: str | None = None,
    lock_version: str = "1",
) -> Lockfile:
    lf = Lockfile(
        id=_uuid(),
        distribution_id=distribution_id,
        profile_id=profile_id,
        build_id=build_id,
        lock_version=lock_version,
        rendered_lock=None,
        content_hash=None,
        created_at=_now(),
    )
    session.add(lf)
    session.flush()
    return lf


def list_lockfiles(
    session: "Session",
    distribution_id: str | None = None,
    build_id: str | None = None,
) -> list[Lockfile]:
    q = select(Lockfile).order_by(Lockfile.created_at.desc())
    if distribution_id is not None:
        q = q.where(Lockfile.distribution_id == distribution_id)
    if build_id is not None:
        q = q.where(Lockfile.build_id == build_id)
    return list(session.scalars(q).all())


def get_lockfile(session: "Session", lockfile_id: str) -> Lockfile:
    lf = session.get(Lockfile, lockfile_id)
    if lf is None:
        raise KeyError(f"Lockfile {lockfile_id!r} not found")
    return lf


def add_lockfile_entry(
    session: "Session",
    lockfile_id: str,
    entry_kind: str,
    entry_key: str,
    version: str = "",
    source_hash: str | None = None,
    extra_json: str | None = None,
) -> LockfileEntry:
    if entry_kind not in VALID_ENTRY_KINDS:
        raise ValueError(
            f"Invalid entry_kind {entry_kind!r}. Valid: {sorted(VALID_ENTRY_KINDS)}"
        )
    existing = session.scalars(
        select(LockfileEntry).where(
            LockfileEntry.lockfile_id == lockfile_id,
            LockfileEntry.entry_kind == entry_kind,
            LockfileEntry.entry_key == entry_key,
        )
    ).first()
    if existing is not None:
        existing.version = version
        existing.source_hash = source_hash
        existing.extra_json = extra_json
    else:
        existing = LockfileEntry(
            id=_uuid(), lockfile_id=lockfile_id,
            entry_kind=entry_kind, entry_key=entry_key,
            version=version, source_hash=source_hash, extra_json=extra_json,
        )
        session.add(existing)
    lf = session.get(Lockfile, lockfile_id)
    if lf is not None:
        lf.content_hash = None
    session.flush()
    return existing


def list_lockfile_entries(
    session: "Session", lockfile_id: str, entry_kind: str | None = None
) -> list[LockfileEntry]:
    q = select(LockfileEntry).where(LockfileEntry.lockfile_id == lockfile_id).order_by(
        LockfileEntry.entry_kind, LockfileEntry.entry_key
    )
    if entry_kind is not None:
        q = q.where(LockfileEntry.entry_kind == entry_kind)
    return list(session.scalars(q).all())


def render_lockfile(session: "Session", lockfile_id: str) -> Lockfile:
    lf = get_lockfile(session, lockfile_id)
    entries = list_lockfile_entries(session, lockfile_id)

    lines = [
        "# OSFabricum Lockfile",
        f"# version = {lf.lock_version}",
        f"# lockfile_id = {lf.id}",
        "",
        "[meta]",
        f"distribution_id = {lf.distribution_id or ''}",
        f"profile_id      = {lf.profile_id or ''}",
        f"build_id        = {lf.build_id or ''}",
        f"lock_version    = {lf.lock_version}",
    ]

    by_kind: dict[str, list[LockfileEntry]] = {}
    for e in entries:
        by_kind.setdefault(e.entry_kind, []).append(e)

    for kind in sorted(by_kind):
        lines.extend(["", f"[{kind}]"])
        for e in by_kind[kind]:
            hash_part = f"  # {e.source_hash}" if e.source_hash else ""
            lines.append(f"{e.entry_key} = {e.version}{hash_part}")

    rendered = "\n".join(lines) + "\n"
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
    lf.rendered_lock = rendered
    lf.content_hash = content_hash
    session.flush()
    return lf


def diff_lockfiles(
    session: "Session", lockfile_a_id: str, lockfile_b_id: str
) -> dict:
    entries_a = {
        (e.entry_kind, e.entry_key): e
        for e in list_lockfile_entries(session, lockfile_a_id)
    }
    entries_b = {
        (e.entry_kind, e.entry_key): e
        for e in list_lockfile_entries(session, lockfile_b_id)
    }
    added = [k for k in entries_b if k not in entries_a]
    removed = [k for k in entries_a if k not in entries_b]
    changed = [
        k for k in entries_a if k in entries_b and entries_a[k].version != entries_b[k].version
    ]
    return {
        "added": [{"kind": k, "key": key, "version": entries_b[(k, key)].version}
                  for k, key in added],
        "removed": [{"kind": k, "key": key, "version": entries_a[(k, key)].version}
                    for k, key in removed],
        "changed": [{"kind": k, "key": key,
                     "from": entries_a[(k, key)].version,
                     "to": entries_b[(k, key)].version}
                    for k, key in changed],
    }
