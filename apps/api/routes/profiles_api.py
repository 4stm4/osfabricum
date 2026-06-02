"""Profile Designer write API (M27).

    GET    /v1/profiles?distribution=NAME
    POST   /v1/profiles
    POST   /v1/profiles/import
    GET    /v1/profiles/{distribution}/{name}
    PATCH  /v1/profiles/{distribution}/{name}
    DELETE /v1/profiles/{distribution}/{name}
    POST   /v1/profiles/{distribution}/{name}/clone
    GET    /v1/profiles/{distribution}/{name}/export
    GET    /v1/profiles/{distribution}/{name}/versions
    POST   /v1/profiles/{distribution}/{name}/versions
    POST   /v1/profiles/{distribution}/diff

A profile is identified by its (distribution, name) pair. Thin client over
``osfabricum.profile`` — no logic here.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from pydantic import BaseModel

from osfabricum import profile as profile_service

router = APIRouter(prefix="/v1/profiles", tags=["profiles"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(status_code=status, detail=str(exc))


class ProfileCreate(BaseModel):
    distribution: str
    name: str
    inherits: str | None = None
    refs: dict[str, Any] = {}
    inputs: dict[str, Any] | None = None


class ProfileUpdate(BaseModel):
    inherits: str | None = None
    refs: dict[str, Any] | None = None
    inputs: dict[str, Any] | None = None


class CloneRequest(BaseModel):
    name: str


class DiffRequest(BaseModel):
    a: str
    b: str


@router.get("")
def list_profiles(request: Request, distribution: Annotated[str, Query()]) -> list[dict[str, Any]]:
    try:
        return profile_service.list_profiles(distribution, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("", status_code=201)
def create_profile(body: ProfileCreate, request: Request) -> dict[str, Any]:
    try:
        return profile_service.create_profile(
            distribution=body.distribution,
            name=body.name,
            inherits=body.inherits,
            refs=body.refs,
            inputs=body.inputs,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/import", status_code=201)
def import_profile(
    request: Request,
    data: Annotated[dict[str, Any], Body()],
    overwrite: bool = False,
) -> dict[str, Any]:
    try:
        return profile_service.import_profile(data, db_url=_db(request), overwrite=overwrite)
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/{distribution}/diff")
def diff_profiles(distribution: str, body: DiffRequest, request: Request) -> dict[str, Any]:
    try:
        return profile_service.diff_profiles(distribution, body.a, body.b, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/{distribution}/{name}")
def get_profile(distribution: str, name: str, request: Request) -> dict[str, Any]:
    try:
        return profile_service.get_profile(distribution, name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/{distribution}/{name}/export")
def export_profile(distribution: str, name: str, request: Request) -> dict[str, Any]:
    try:
        return profile_service.export_profile(distribution, name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/{distribution}/{name}/versions")
def list_versions(distribution: str, name: str, request: Request) -> list[dict[str, Any]]:
    try:
        return profile_service.list_versions(distribution, name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/{distribution}/{name}/versions", status_code=201)
def create_version(distribution: str, name: str, request: Request) -> dict[str, Any]:
    try:
        return profile_service.create_version(distribution, name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/{distribution}/{name}")
def update_profile(
    distribution: str, name: str, body: ProfileUpdate, request: Request
) -> dict[str, Any]:
    provided = body.model_fields_set
    kwargs: dict[str, Any] = {}
    if "inherits" in provided:
        kwargs["inherits"] = body.inherits
    if "inputs" in provided:
        kwargs["inputs"] = body.inputs
    if body.refs:
        kwargs["refs"] = body.refs
    try:
        return profile_service.update_profile(distribution, name, db_url=_db(request), **kwargs)
    except ValueError as exc:
        raise _guard(exc) from exc


@router.delete("/{distribution}/{name}", status_code=204)
def delete_profile(distribution: str, name: str, request: Request) -> Response:
    try:
        profile_service.delete_profile(distribution, name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc
    return Response(status_code=204)


@router.post("/{distribution}/{name}/clone", status_code=201)
def clone_profile(
    distribution: str, name: str, body: CloneRequest, request: Request
) -> dict[str, Any]:
    try:
        return profile_service.clone_profile(distribution, name, body.name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc
