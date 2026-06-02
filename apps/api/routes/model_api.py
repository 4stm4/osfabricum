"""REST API for the Universal OS Builder Model (M25).

    GET /v1/distribution-classes   — list the OS classes the factory supports

Distribution classes are a fixed enumeration seeded by migration ``0006``; the
``class`` field on distributions/profiles is exposed by the M26/M27 designers.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from osfabricum.db.models import DistributionClass
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
