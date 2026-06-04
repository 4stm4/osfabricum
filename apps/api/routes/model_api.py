"""REST API for the Universal OS Builder Model (M25) + wizard selectors.

    GET /v1/distribution-classes   — the OS classes the factory supports
    GET /v1/kernels                — registered kernels (filter by arch/board)
    GET /v1/package-sets           — package sets (filter by distribution)

The kernel/package-set lists back the Build Wizard dropdowns so the user picks
from real catalog entries instead of typing a name.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_, select

from osfabricum.db.models import (
    Architecture,
    Board,
    BootScheme,
    Distribution,
    DistributionClass,
    Kernel,
    PackageSet,
)
from osfabricum.db.session import sync_session

router = APIRouter(prefix="/v1", tags=["model"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


class DistributionClassItem(BaseModel):
    id: str
    name: str
    description: str | None


@router.get("/distribution-classes", response_model=list[DistributionClassItem])
def list_distribution_classes(request: Request) -> list[DistributionClassItem]:
    with sync_session(_db(request)) as session:
        rows = session.scalars(select(DistributionClass).order_by(DistributionClass.name)).all()
    return [DistributionClassItem(id=r.id, name=r.name, description=r.description) for r in rows]


@router.get("/kernels")
def list_kernels(
    request: Request,
    arch: Annotated[str | None, Query(description="Filter by architecture name")] = None,
    board: Annotated[str | None, Query(description="Filter by board name (uses its arch)")] = None,
) -> list[dict[str, Any]]:
    """List registered kernels, optionally scoped to a board's / an architecture."""
    with sync_session(_db(request)) as s:
        arch_id: str | None = None
        if board:
            b = s.scalar(select(Board).where(Board.name == board))
            arch_id = b.arch_id if b is not None else None
        elif arch:
            a = s.scalar(select(Architecture).where(Architecture.name == arch))
            arch_id = a.id if a is not None else None
        q = select(Kernel)
        if arch_id is not None:
            q = q.where(Kernel.arch_id == arch_id)
        kernels = s.scalars(q.order_by(Kernel.name, Kernel.version)).all()
        arch_names = {a.id: a.name for a in s.scalars(select(Architecture)).all()}
        return [
            {"id": k.id, "name": k.name, "version": k.version, "arch": arch_names.get(k.arch_id)}
            for k in kernels
        ]


@router.get("/package-sets")
def list_package_sets(
    request: Request,
    distribution: Annotated[str | None, Query(description="Filter by distribution name")] = None,
) -> list[dict[str, Any]]:
    """List package sets; with ``distribution`` returns its sets + global ones."""
    with sync_session(_db(request)) as s:
        q = select(PackageSet)
        if distribution:
            d = s.scalar(select(Distribution).where(Distribution.name == distribution))
            dist_id = d.id if d is not None else None
            q = q.where(
                or_(PackageSet.distribution_id == dist_id, PackageSet.distribution_id.is_(None))
            )
        rows = s.scalars(q.order_by(PackageSet.name)).all()
        return [
            {"id": ps.id, "name": ps.name, "distribution_id": ps.distribution_id} for ps in rows
        ]


@router.get("/boot-schemes")
def list_boot_schemes(request: Request) -> list[dict[str, Any]]:
    """List boot schemes (backs the Boot Chain Designer dropdown)."""
    with sync_session(_db(request)) as s:
        rows = s.scalars(select(BootScheme).order_by(BootScheme.name)).all()
        return [{"id": b.id, "name": b.name, "description": b.description} for b in rows]
