"""Business logic for M69 — Public Artifact Repository / Release Publishing."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import (
    PublishedRelease,
    ReleaseArtifact,
    ReleaseChannel,
    Repository,
    RepositoryIndex,
    _now,
    _uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_REPO_KINDS: frozenset[str] = frozenset({"package", "image", "firmware", "release"})
VALID_RELEASE_STATUSES: frozenset[str] = frozenset({"draft", "published", "withdrawn"})
VALID_RELEASE_ARTIFACT_ROLES: frozenset[str] = frozenset(
    {"image", "rootfs", "bootloader", "kernel", "initramfs", "sbom",
     "checksum", "signature", "attestation", "other"}
)


def list_release_channels(session: "Session") -> list[ReleaseChannel]:
    return list(
        session.scalars(
            select(ReleaseChannel).order_by(ReleaseChannel.display_order)
        ).all()
    )


def create_repository(
    session: "Session",
    name: str,
    repo_kind: str = "image",
    label: str = "",
    description: str = "",
    base_url: str | None = None,
    sign_key_id: str | None = None,
) -> Repository:
    if repo_kind not in VALID_REPO_KINDS:
        raise ValueError(
            f"Invalid repo_kind {repo_kind!r}. Valid: {sorted(VALID_REPO_KINDS)}"
        )
    repo = Repository(
        id=_uuid(), name=name, label=label, description=description,
        repo_kind=repo_kind, base_url=base_url, sign_key_id=sign_key_id,
        is_published=False, created_at=_now(), updated_at=_now(),
    )
    session.add(repo)
    session.flush()
    return repo


def list_repositories(
    session: "Session", repo_kind: str | None = None
) -> list[Repository]:
    q = select(Repository).order_by(Repository.name)
    if repo_kind is not None:
        q = q.where(Repository.repo_kind == repo_kind)
    return list(session.scalars(q).all())


def get_repository(session: "Session", repo_id: str) -> Repository:
    r = session.get(Repository, repo_id)
    if r is None:
        raise KeyError(f"Repository {repo_id!r} not found")
    return r


def create_release(
    session: "Session",
    channel: str,
    version: str,
    distribution_id: str | None = None,
) -> PublishedRelease:
    rel = PublishedRelease(
        id=_uuid(), distribution_id=distribution_id,
        channel=channel, version=version, status="draft",
        rendered_release_manifest=None, content_hash=None, rendered_at=None,
        created_at=_now(), updated_at=_now(),
    )
    session.add(rel)
    session.flush()
    return rel


def list_releases(
    session: "Session",
    channel: str | None = None,
    status: str | None = None,
    distribution_id: str | None = None,
) -> list[PublishedRelease]:
    q = select(PublishedRelease).order_by(PublishedRelease.created_at.desc())
    if channel is not None:
        q = q.where(PublishedRelease.channel == channel)
    if status is not None:
        q = q.where(PublishedRelease.status == status)
    if distribution_id is not None:
        q = q.where(PublishedRelease.distribution_id == distribution_id)
    return list(session.scalars(q).all())


def get_release(session: "Session", release_id: str) -> PublishedRelease:
    r = session.get(PublishedRelease, release_id)
    if r is None:
        raise KeyError(f"PublishedRelease {release_id!r} not found")
    return r


def promote_release(
    session: "Session", release_id: str, status: str
) -> PublishedRelease:
    if status not in VALID_RELEASE_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Valid: {sorted(VALID_RELEASE_STATUSES)}"
        )
    rel = get_release(session, release_id)
    rel.status = status
    rel.updated_at = _now()
    _invalidate(rel)
    session.flush()
    return rel


def add_release_artifact(
    session: "Session",
    release_id: str,
    artifact_role: str,
    artifact_id: str | None = None,
    artifact_uri: str | None = None,
) -> ReleaseArtifact:
    if artifact_role not in VALID_RELEASE_ARTIFACT_ROLES:
        raise ValueError(
            f"Invalid artifact_role {artifact_role!r}. "
            f"Valid: {sorted(VALID_RELEASE_ARTIFACT_ROLES)}"
        )
    existing = session.scalars(
        select(ReleaseArtifact).where(
            ReleaseArtifact.release_id == release_id,
            ReleaseArtifact.artifact_role == artifact_role,
        )
    ).first()
    if existing is not None:
        existing.artifact_id = artifact_id
        existing.artifact_uri = artifact_uri
    else:
        existing = ReleaseArtifact(
            id=_uuid(), release_id=release_id, artifact_role=artifact_role,
            artifact_id=artifact_id, artifact_uri=artifact_uri,
        )
        session.add(existing)
    rel = session.get(PublishedRelease, release_id)
    if rel is not None:
        _invalidate(rel)
        rel.updated_at = _now()
    session.flush()
    return existing


def render_release_manifest(session: "Session", release_id: str) -> PublishedRelease:
    rel = get_release(session, release_id)
    artifacts = session.scalars(
        select(ReleaseArtifact).where(ReleaseArtifact.release_id == release_id)
        .order_by(ReleaseArtifact.artifact_role)
    ).all()

    lines = [
        "# OSFabricum Release Manifest",
        f"# {rel.channel}/{rel.version}",
        "",
        "[release]",
        f"id              = {rel.id}",
        f"channel         = {rel.channel}",
        f"version         = {rel.version}",
        f"status          = {rel.status}",
        f"distribution_id = {rel.distribution_id or ''}",
        "",
        "[artifacts]",
    ]
    for a in artifacts:
        lines.append(
            f"{a.artifact_role:16s} = {a.artifact_uri or a.artifact_id or 'unset'}"
        )

    rendered = "\n".join(lines) + "\n"
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()
    rel.rendered_release_manifest = rendered
    rel.content_hash = content_hash
    rel.rendered_at = datetime.utcnow()
    rel.updated_at = _now()
    session.flush()
    return rel


def index_repository(
    session: "Session", repo_id: str, channel: str
) -> RepositoryIndex:
    repo = get_repository(session, repo_id)
    releases = list_releases(session, channel=channel, status="published")

    lines = [
        f"# OSFabricum Repository Index",
        f"# repository = {repo.name}",
        f"# channel    = {channel}",
        f"# kind       = {repo.repo_kind}",
        "",
        "[releases]",
    ]
    for r in releases:
        lines.append(f"{r.version} = {r.id}")

    rendered = "\n".join(lines) + "\n"
    content_hash = "sha256:" + hashlib.sha256(rendered.encode()).hexdigest()

    existing = session.scalars(
        select(RepositoryIndex).where(
            RepositoryIndex.repository_id == repo_id,
            RepositoryIndex.channel == channel,
        )
    ).first()
    if existing is not None:
        existing.rendered_index = rendered
        existing.content_hash = content_hash
        existing.indexed_at = datetime.utcnow()
    else:
        existing = RepositoryIndex(
            id=_uuid(), repository_id=repo_id, channel=channel,
            rendered_index=rendered, content_hash=content_hash,
            indexed_at=datetime.utcnow(), created_at=_now(),
        )
        session.add(existing)
    session.flush()
    return existing


def _invalidate(rel: PublishedRelease) -> None:
    rel.content_hash = None
    rel.rendered_at = None
    rel.rendered_release_manifest = None
