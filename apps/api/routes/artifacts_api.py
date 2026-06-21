"""REST API routes for artifacts (M20).

GET /v1/artifacts           — search artifacts
GET /v1/artifacts/{id}      — artifact metadata
GET /v1/artifacts/{id}/download — download artifact blob
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.layout import blob_path

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url
    except AttributeError:
        return None


class ArtifactItem(BaseModel):
    id: str
    kind: str
    name: str
    version: str | None
    arch: str | None
    store_key: str
    blob_sha256: str
    size_bytes: int | None
    media_type: str | None
    retention_class: str
    pinned: bool
    input_hash: str | None
    created_at: str | None
    metadata: dict[str, Any] | None
    producer_build_id: str | None = None


@router.get("", response_model=list[ArtifactItem])
def search_artifacts(
    request: Request,
    kind: Annotated[str | None, Query(description="Filter by kind")] = None,
    name: Annotated[str | None, Query(description="Filter by name prefix")] = None,
    arch: Annotated[str | None, Query(description="Filter by arch")] = None,
    retention_class: Annotated[str | None, Query()] = None,
    pinned: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ArtifactItem]:
    """Search artifacts with optional filters."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        q = select(Artifact).order_by(Artifact.created_at.desc())
        if kind:
            q = q.where(Artifact.kind == kind)
        if name:
            q = q.where(Artifact.name.startswith(name))
        if arch:
            q = q.where(Artifact.arch == arch)
        if retention_class:
            q = q.where(Artifact.retention_class == retention_class)
        if pinned is not None:
            q = q.where(Artifact.pinned == pinned)
        q = q.offset(offset).limit(limit)
        rows = session.scalars(q).all()
        return [_to_item(r) for r in rows]


@router.get("/{artifact_id}", response_model=ArtifactItem)
def get_artifact(artifact_id: str, request: Request) -> ArtifactItem:
    """Return metadata for a single artifact."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
        if art is None:
            raise HTTPException(status_code=404, detail=f"Artifact {artifact_id!r} not found")
        return _to_item(art)


@router.get("/{artifact_id}/download")
def download_artifact(artifact_id: str, request: Request) -> FileResponse:
    """Download artifact blob as a file."""
    db_url = _db(request)
    try:
        store_root = Path(request.app.state.settings.store.root)
    except AttributeError:
        raise HTTPException(status_code=503, detail="Store not configured")
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
        if art is None:
            raise HTTPException(status_code=404, detail=f"Artifact {artifact_id!r} not found")
        path = blob_path(store_root, art.blob_sha256)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Blob file not found in store")
        _ext = {"application/gzip": ".img.gz", "application/x-xz": ".img.xz"}
        ext = _ext.get(art.media_type or "", "")
        build_prefix = art.producer_build_id[:8] if art.producer_build_id else artifact_id[:8]
        date_str = art.created_at.strftime("%Y%m%d") if art.created_at else ""
        suffix = f"-{date_str}-{build_prefix}" if date_str else f"-{build_prefix}"
        filename = f"{art.name}{suffix}{ext}" if art.name else f"{artifact_id}{ext}"
        return FileResponse(
            path=str(path),
            filename=filename,
            media_type=art.media_type or "application/octet-stream",
        )


def _to_item(art: Artifact) -> ArtifactItem:
    return ArtifactItem(
        id=art.id,
        kind=art.kind,
        name=art.name,
        version=art.version,
        arch=art.arch,
        store_key=art.store_key,
        blob_sha256=art.blob_sha256,
        size_bytes=art.size_bytes,
        media_type=art.media_type,
        retention_class=art.retention_class,
        pinned=art.pinned,
        input_hash=art.input_hash,
        created_at=art.created_at.isoformat() if art.created_at else None,
        metadata=art.metadata_json,
        producer_build_id=art.producer_build_id,
    )
