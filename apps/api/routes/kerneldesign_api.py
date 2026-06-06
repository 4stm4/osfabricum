"""Kernel / Driver Designer write API (M33).

    POST /v1/kconfig-indexes                              — ingest a Kconfig index
    GET  /v1/kconfig-indexes/{id}/options?q=              — search symbols
    GET  /v1/kconfig-indexes/{id}/options/{symbol}        — symbol + dependencies
    POST /v1/kernel-configs/resolve|validate|render|diff  — config operations
    POST /v1/kernel-configs/save-preset                   — store a resolved config
    GET/POST /v1/driver-bundles ; POST /{id}/options|modules|firmware|dt-overlays
    GET  /v1/driver-bundles/{id}/resolve
    GET/POST /v1/external-modules ; POST /{id}/recipes

Reads and pure computations (search / resolve / validate / render / diff) are
public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from osfabricum import kerneldesign as kd
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(prefix="/v1", tags=["kernel-driver"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc))


# --- request models ---


class IndexRequest(BaseModel):
    kernel_id: str
    arch: str
    source_ref: str | None = None
    symbols: list[dict[str, Any]]


class ResolveRequest(BaseModel):
    index_id: str
    requested: dict[str, str]


class RenderRequest(BaseModel):
    index_id: str
    resolved: dict[str, str]


class DiffRequest(BaseModel):
    a: str
    b: str


class PresetRequest(BaseModel):
    name: str
    content: str
    kernel_id: str | None = None


class BundleRequest(BaseModel):
    name: str
    kernel_id: str | None = None
    description: str | None = None


class BundleItem(BaseModel):
    value: str | None = "y"
    name: str


class ExternalModuleRequest(BaseModel):
    name: str
    source_uri: str | None = None
    source_ref: str | None = None


class RecipeRequest(BaseModel):
    kernel_id: str
    build_system: str = "kbuild"
    steps: dict[str, Any] | None = None


# --- Kconfig index + options ---


@router.get("/kconfig-indexes")
def list_indexes(request: Request) -> list[dict[str, Any]]:
    return kd.list_indexes(db_url=_db(request))


@router.post("/kconfig-indexes", status_code=201)
def create_index(
    body: IndexRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    return kd.index_kconfig(
        kernel_id=body.kernel_id,
        arch=body.arch,
        source_ref=body.source_ref,
        symbols=body.symbols,
        db_url=_db(request),
    )


@router.get("/kconfig-indexes/{index_id}/options")
def search_opts(index_id: str, request: Request, q: str = Query("")) -> list[dict[str, Any]]:
    try:
        return kd.search_options(index_id, q, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/kconfig-indexes/{index_id}/options/{symbol}")
def get_opt(index_id: str, symbol: str, request: Request) -> dict[str, Any]:
    try:
        return kd.get_option(index_id, symbol, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


# --- config operations (pure, public) ---


@router.post("/kernel-configs/resolve")
def resolve_cfg(body: ResolveRequest, request: Request) -> dict[str, Any]:
    try:
        return kd.resolve_config(body.index_id, body.requested, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/kernel-configs/validate")
def validate_cfg(body: ResolveRequest, request: Request) -> dict[str, Any]:
    try:
        return kd.validate_config(body.index_id, body.requested, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/kernel-configs/render")
def render_cfg(body: RenderRequest, request: Request) -> dict[str, Any]:
    try:
        return kd.render_config(body.index_id, body.resolved, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/kernel-configs/diff")
def diff_cfg(body: DiffRequest) -> dict[str, Any]:
    return kd.diff_config(body.a, body.b)


@router.post("/kernel-configs/save-preset", status_code=201)
def save_preset(
    body: PresetRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    return kd.save_preset(body.name, body.content, kernel_id=body.kernel_id, db_url=_db(request))


# --- driver bundles ---


@router.get("/driver-bundles")
def list_bundles(request: Request) -> list[dict[str, Any]]:
    return kd.list_driver_bundles(db_url=_db(request))


@router.post("/driver-bundles", status_code=201)
def create_bundle(
    body: BundleRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return kd.create_driver_bundle(
            body.name, kernel_id=body.kernel_id, description=body.description, db_url=_db(request)
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/driver-bundles/{bundle_id}/resolve")
def resolve_bundle(bundle_id: str, request: Request) -> dict[str, Any]:
    try:
        return kd.resolve_driver_bundle(bundle_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/driver-bundles/{bundle_id}/options", status_code=201)
def add_option(
    bundle_id: str, body: BundleItem, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return kd.add_bundle_option(bundle_id, body.name, body.value or "y", db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/driver-bundles/{bundle_id}/modules", status_code=201)
def add_module(
    bundle_id: str, body: BundleItem, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return kd.add_bundle_module(bundle_id, body.name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/driver-bundles/{bundle_id}/firmware", status_code=201)
def add_firmware(
    bundle_id: str, body: BundleItem, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return kd.add_bundle_firmware(bundle_id, body.name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/driver-bundles/{bundle_id}/dt-overlays", status_code=201)
def add_overlay(
    bundle_id: str, body: BundleItem, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return kd.add_bundle_dt_overlay(bundle_id, body.name, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


# --- external modules ---


@router.get("/external-modules")
def list_ext(request: Request) -> list[dict[str, Any]]:
    return kd.list_external_modules(db_url=_db(request))


@router.post("/external-modules", status_code=201)
def create_ext(
    body: ExternalModuleRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return kd.create_external_module(
            body.name, source_uri=body.source_uri, source_ref=body.source_ref, db_url=_db(request)
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/external-modules/{module_id}/recipes", status_code=201)
def add_recipe(
    module_id: str, body: RecipeRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return kd.add_external_module_recipe(
            module_id,
            body.kernel_id,
            build_system=body.build_system,
            steps=body.steps,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc
