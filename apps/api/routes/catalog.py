"""REST API routes for the catalog (M20).

GET /v1/catalog/distributions   — list distributions
GET /v1/catalog/boards          — list boards
GET /v1/catalog/packages        — list packages (with filters)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from osfabricum.db.models import Architecture, Board, Distribution, Package, PackageVersion
from osfabricum.db.session import sync_session

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DistributionItem(BaseModel):
    id: str
    name: str
    description: str | None
    default_channel: str


class BoardItem(BaseModel):
    id: str
    name: str
    arch: str
    boot_scheme: str
    firmware_required: bool


class PackageItem(BaseModel):
    id: str
    name: str
    package_type: str
    versions: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/distributions", response_model=list[DistributionItem])
def list_distributions(request: Request) -> list[DistributionItem]:
    """List all distributions in the registry."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        rows = session.scalars(select(Distribution).order_by(Distribution.name)).all()
        return [
            DistributionItem(
                id=r.id,
                name=r.name,
                description=r.description,
                default_channel=r.default_channel,
            )
            for r in rows
        ]


@router.get("/boards", response_model=list[BoardItem])
def list_boards(
    request: Request,
    arch: Annotated[str | None, Query(description="Filter by architecture")] = None,
) -> list[BoardItem]:
    """List boards, optionally filtered by architecture."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        q = select(Board).order_by(Board.name)
        arch_map: dict[str, str] = {
            a.id: a.name for a in session.scalars(select(Architecture)).all()
        }
        if arch:
            arch_row = session.scalar(select(Architecture).where(Architecture.name == arch))
            if arch_row is None:
                return []  # unknown arch → no matching boards
            q = q.where(Board.arch_id == arch_row.id)
        boards = session.scalars(q).all()
        return [
            BoardItem(
                id=b.id,
                name=b.name,
                arch=arch_map.get(b.arch_id, b.arch_id),
                boot_scheme=b.boot_scheme,
                firmware_required=b.firmware_required,
            )
            for b in boards
        ]


@router.get("/packages", response_model=list[PackageItem])
def list_packages(
    request: Request,
    name: Annotated[str | None, Query(description="Filter by name prefix")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PackageItem]:
    """List packages with their available versions."""
    db_url = _db(request)
    with sync_session(db_url) as session:
        q = select(Package).order_by(Package.name).limit(limit)
        if name:
            q = q.where(Package.name.startswith(name))
        packages = session.scalars(q).all()
        result = []
        for pkg in packages:
            versions = session.scalars(
                select(PackageVersion).where(PackageVersion.package_id == pkg.id)
            ).all()
            result.append(
                PackageItem(
                    id=pkg.id,
                    name=pkg.name,
                    package_type=pkg.package_type,
                    versions=[
                        {
                            "id": pv.id,
                            "version": pv.version,
                            "status": pv.status,
                            "artifact_id": pv.artifact_id,
                        }
                        for pv in versions
                    ],
                )
            )
        return result
