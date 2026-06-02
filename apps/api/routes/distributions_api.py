"""Distribution Designer write API (M26).

    GET    /v1/distributions
    POST   /v1/distributions
    GET    /v1/distributions/{id}
    PATCH  /v1/distributions/{id}
    DELETE /v1/distributions/{id}
    POST   /v1/distributions/{id}/clone
    POST   /v1/distributions/import
    GET    /v1/distributions/{id}/export

The routes are a thin client over ``osfabricum.distribution`` — no logic lives
here. ``{id}`` accepts a distribution id or name. Domain errors surface as
HTTP 404 (not found) or 400 (everything else).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from osfabricum import distribution as dist_service

router = APIRouter(prefix="/v1/distributions", tags=["distributions"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(status_code=status, detail=str(exc))


class DistributionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    description: str | None = None
    default_channel: str = "dev"
    class_name: str | None = Field(default=None, alias="class")
    metadata: dict[str, Any] | None = None


class DistributionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    description: str | None = None
    default_channel: str | None = None
    class_name: str | None = Field(default=None, alias="class")
    metadata: dict[str, Any] | None = None


class CloneRequest(BaseModel):
    name: str


@router.get("")
def list_distributions(request: Request) -> list[dict[str, Any]]:
    return dist_service.list_distributions(db_url=_db(request))


@router.post("", status_code=201)
def create_distribution(body: DistributionCreate, request: Request) -> dict[str, Any]:
    try:
        return dist_service.create_distribution(
            name=body.name,
            description=body.description,
            default_channel=body.default_channel,
            class_name=body.class_name,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/import", status_code=201)
def import_distribution(
    request: Request,
    data: Annotated[dict[str, Any], Body()],
    overwrite: bool = False,
) -> dict[str, Any]:
    try:
        return dist_service.import_distribution(data, db_url=_db(request), overwrite=overwrite)
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/{dist_id}")
def get_distribution(dist_id: str, request: Request) -> dict[str, Any]:
    try:
        return dist_service.get_distribution(dist_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/{dist_id}/export")
def export_distribution(dist_id: str, request: Request) -> dict[str, Any]:
    try:
        return dist_service.export_distribution(dist_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/{dist_id}")
def update_distribution(dist_id: str, body: DistributionUpdate, request: Request) -> dict[str, Any]:
    provided = body.model_fields_set
    kwargs: dict[str, Any] = {}
    if "description" in provided:
        kwargs["description"] = body.description
    if "default_channel" in provided:
        kwargs["default_channel"] = body.default_channel
    if "class_name" in provided:
        kwargs["class_name"] = body.class_name
    if "metadata" in provided:
        kwargs["metadata"] = body.metadata
    try:
        return dist_service.update_distribution(dist_id, db_url=_db(request), **kwargs)
    except ValueError as exc:
        raise _guard(exc) from exc


@router.delete("/{dist_id}", status_code=204)
def delete_distribution(dist_id: str, request: Request) -> Response:
    try:
        dist_service.delete_distribution(dist_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc
    return Response(status_code=204)


@router.post("/{dist_id}/clone", status_code=201)
def clone_distribution(dist_id: str, body: CloneRequest, request: Request) -> dict[str, Any]:
    try:
        return dist_service.clone_distribution(dist_id, body.name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc
