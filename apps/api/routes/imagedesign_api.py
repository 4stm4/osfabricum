"""Filesystem / Image Recipe Designer API (M34).

    GET/POST /v1/filesystem-profiles
    GET/POST /v1/size-policies
    GET/POST /v1/partition-layouts ; POST /{id}/partitions
    GET/POST /v1/image-recipes ; GET /{id} (resolve) ; POST /{id}/estimate
    POST /v1/image-recipes/{id}/outputs|mounts|overlays ; PATCH /{id}/targets

Reads and the (pure) size estimate are public; mutations require auth
(WriteAuthDep, G-24).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import imagedesign as imd
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(prefix="/v1", tags=["image-recipe"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc))


# --- request models ---


class FilesystemRequest(BaseModel):
    name: str
    fs_type: str
    label: str | None = None
    mount_point: str | None = None
    read_only: bool = False
    compression: str | None = None
    options: dict[str, Any] | None = None


class SizePolicyRequest(BaseModel):
    name: str
    free_space_pct: int = 0
    min_free_mb: int = 0
    align_mb: int = 4
    reserve_mb: int = 1
    grow_to_fit: bool = True


class LayoutRequest(BaseModel):
    name: str
    board_id: str | None = None


class PartitionRequest(BaseModel):
    name: str
    role: str
    filesystem_id: str | None = None
    size_mb: int | None = None
    grow: bool = False
    position: int | None = None
    flags: dict[str, Any] | None = None


class RecipeRequest(BaseModel):
    name: str
    distribution_id: str | None = None
    output_format: str = "raw"
    description: str | None = None
    partition_layout_id: str | None = None
    size_policy_id: str | None = None
    root_filesystem_id: str | None = None


class TargetsRequest(BaseModel):
    partition_layout_id: str | None = None
    size_policy_id: str | None = None
    root_filesystem_id: str | None = None


class OutputRequest(BaseModel):
    output_format: str
    compression: str | None = None
    filename_template: str | None = None
    position: int | None = None


class MountRequest(BaseModel):
    source: str
    target: str
    fstype: str
    options: str | None = None
    position: int | None = None


class OverlayRequest(BaseModel):
    target: str
    lower_dir: str
    upper_dir: str
    work_dir: str
    persistent: bool = False


class EstimateRequest(BaseModel):
    total_disk_mb: int | None = None


# --- filesystem profiles ---


@router.get("/filesystem-profiles")
def list_filesystems(request: Request) -> list[dict[str, Any]]:
    return imd.list_filesystem_profiles(db_url=_db(request))


@router.post("/filesystem-profiles", status_code=201)
def create_filesystem(
    body: FilesystemRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.create_filesystem_profile(
            body.name,
            body.fs_type,
            label=body.label,
            mount_point=body.mount_point,
            read_only=body.read_only,
            compression=body.compression,
            options=body.options,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- size policies ---


@router.get("/size-policies")
def list_sizes(request: Request) -> list[dict[str, Any]]:
    return imd.list_size_policies(db_url=_db(request))


@router.post("/size-policies", status_code=201)
def create_size(
    body: SizePolicyRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.create_size_policy(
            body.name,
            free_space_pct=body.free_space_pct,
            min_free_mb=body.min_free_mb,
            align_mb=body.align_mb,
            reserve_mb=body.reserve_mb,
            grow_to_fit=body.grow_to_fit,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- partition layouts ---


@router.get("/partition-layouts")
def list_layouts(request: Request) -> list[dict[str, Any]]:
    return imd.list_partition_layouts(db_url=_db(request))


@router.post("/partition-layouts", status_code=201)
def create_layout(
    body: LayoutRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.create_partition_layout(body.name, board_id=body.board_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/partition-layouts/{layout_id}/partitions", status_code=201)
def add_partition(
    layout_id: str, body: PartitionRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.add_partition(
            layout_id,
            body.name,
            body.role,
            filesystem_id=body.filesystem_id,
            size_mb=body.size_mb,
            grow=body.grow,
            position=body.position,
            flags=body.flags,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- image recipes ---


@router.get("/image-recipes")
def list_recipes(request: Request) -> list[dict[str, Any]]:
    return imd.list_recipes(db_url=_db(request))


@router.post("/image-recipes", status_code=201)
def create_recipe(
    body: RecipeRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.create_recipe(
            body.name,
            distribution_id=body.distribution_id,
            output_format=body.output_format,
            description=body.description,
            partition_layout_id=body.partition_layout_id,
            size_policy_id=body.size_policy_id,
            root_filesystem_id=body.root_filesystem_id,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/image-recipes/{recipe_id}")
def resolve_recipe(recipe_id: str, request: Request) -> dict[str, Any]:
    try:
        return imd.resolve_recipe(recipe_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/image-recipes/{recipe_id}/estimate")
def estimate_recipe(recipe_id: str, body: EstimateRequest, request: Request) -> dict[str, Any]:
    try:
        return imd.estimate_recipe(recipe_id, total_disk_mb=body.total_disk_mb, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.patch("/image-recipes/{recipe_id}/targets")
def set_targets(
    recipe_id: str, body: TargetsRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.set_recipe_targets(
            recipe_id,
            partition_layout_id=body.partition_layout_id,
            size_policy_id=body.size_policy_id,
            root_filesystem_id=body.root_filesystem_id,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/image-recipes/{recipe_id}/outputs", status_code=201)
def add_output(
    recipe_id: str, body: OutputRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.add_output(
            recipe_id,
            body.output_format,
            compression=body.compression,
            filename_template=body.filename_template,
            position=body.position,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/image-recipes/{recipe_id}/mounts", status_code=201)
def add_mount(
    recipe_id: str, body: MountRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.add_mount(
            recipe_id,
            body.source,
            body.target,
            body.fstype,
            options=body.options,
            position=body.position,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/image-recipes/{recipe_id}/overlays", status_code=201)
def add_overlay(
    recipe_id: str, body: OverlayRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return imd.add_overlay(
            recipe_id,
            body.target,
            body.lower_dir,
            body.upper_dir,
            body.work_dir,
            persistent=body.persistent,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc
