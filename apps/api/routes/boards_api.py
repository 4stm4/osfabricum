"""Board/BSP API (M30).

    GET    /v1/boards/{id}/bsp          — get board with all BSP data
    GET    /v1/soc-families              — list SoC families
    POST   /v1/soc-families              — create SoC family
    GET    /v1/boards/{id}/revisions     — list board revisions
    POST   /v1/boards/{id}/revisions     — create board revision
    POST   /v1/boards/{id}/firmware      — add firmware blob
    POST   /v1/boards/{id}/device-trees  — add device tree
    POST   /v1/boards/{id}/flash-methods — add flash method
    POST   /v1/boards/{id}/test-methods  — add test method
    POST   /v1/boards/{id}/probe-profiles — add probe profile
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import board as board_service
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(prefix="/v1", tags=["boards"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(status_code=status, detail=str(exc))


# SoC Families

class SocFamilyCreate(BaseModel):
    name: str
    vendor: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


@router.get("/soc-families")
def list_soc_families(request: Request) -> list[dict[str, Any]]:
    """List all SoC families."""
    return board_service.list_soc_families(db_url=_db(request))


@router.post("/soc-families", status_code=201)
def create_soc_family(
    body: SocFamilyCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Create a new SoC family."""
    try:
        return board_service.create_soc_family(
            name=body.name,
            vendor=body.vendor,
            description=body.description,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Board Revisions

class BoardRevisionCreate(BaseModel):
    revision: str
    soc_family_id: str | None = None
    description: str | None = None
    is_default: bool = False
    metadata: dict[str, Any] | None = None


@router.get("/boards/{board_id}/revisions")
def list_board_revisions(board_id: str, request: Request) -> list[dict[str, Any]]:
    """List all revisions for a board."""
    return board_service.list_board_revisions(board_id, db_url=_db(request))


@router.post("/boards/{board_id}/revisions", status_code=201)
def create_board_revision(
    board_id: str, body: BoardRevisionCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Create a new board revision."""
    try:
        return board_service.create_board_revision(
            board_id=board_id,
            revision=body.revision,
            soc_family_id=body.soc_family_id,
            description=body.description,
            is_default=body.is_default,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Board BSP (full view)

@router.get("/boards/{board_id}/bsp")
def get_board_bsp(board_id: str, request: Request) -> dict[str, Any]:
    """Get board with all BSP data (revisions, firmware, DTBs, methods)."""
    try:
        return board_service.get_board_with_bsp(board_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


# Board Firmware

class BoardFirmwareCreate(BaseModel):
    filename: str
    source_uri: str | None = None
    source_ref: str | None = None
    expected_hash: str | None = None
    required: bool = True
    placement: str | None = None
    board_revision_id: str | None = None
    metadata: dict[str, Any] | None = None


@router.post("/boards/{board_id}/firmware", status_code=201)
def add_board_firmware(
    board_id: str, body: BoardFirmwareCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Add firmware blob to a board."""
    try:
        return board_service.add_board_firmware(
            board_id=board_id,
            filename=body.filename,
            source_uri=body.source_uri,
            source_ref=body.source_ref,
            expected_hash=body.expected_hash,
            required=body.required,
            placement=body.placement,
            board_revision_id=body.board_revision_id,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Board Device Trees

class BoardDeviceTreeCreate(BaseModel):
    filename: str
    dtb_type: str  # base or overlay
    source_uri: str | None = None
    source_ref: str | None = None
    expected_hash: str | None = None
    required: bool = True
    placement: str | None = None
    board_revision_id: str | None = None
    metadata: dict[str, Any] | None = None


@router.post("/boards/{board_id}/device-trees", status_code=201)
def add_board_device_tree(
    board_id: str, body: BoardDeviceTreeCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Add device tree to a board."""
    try:
        return board_service.add_board_device_tree(
            board_id=board_id,
            filename=body.filename,
            dtb_type=body.dtb_type,
            source_uri=body.source_uri,
            source_ref=body.source_ref,
            expected_hash=body.expected_hash,
            required=body.required,
            placement=body.placement,
            board_revision_id=body.board_revision_id,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Board Flash Methods

class BoardFlashMethodCreate(BaseModel):
    method_name: str
    description: str | None = None
    command_template: str | None = None
    requires_tools: list[str] | None = None
    device_pattern: str | None = None
    is_default: bool = False
    board_revision_id: str | None = None
    metadata: dict[str, Any] | None = None


@router.post("/boards/{board_id}/flash-methods", status_code=201)
def add_board_flash_method(
    board_id: str, body: BoardFlashMethodCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Add flash method to a board."""
    try:
        return board_service.add_board_flash_method(
            board_id=board_id,
            method_name=body.method_name,
            description=body.description,
            command_template=body.command_template,
            requires_tools=body.requires_tools,
            device_pattern=body.device_pattern,
            is_default=body.is_default,
            board_revision_id=body.board_revision_id,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Board Test Methods

class BoardTestMethodCreate(BaseModel):
    method_name: str
    description: str | None = None
    test_command: str | None = None
    requires_tools: list[str] | None = None
    timeout_seconds: int | None = None
    is_default: bool = False
    board_revision_id: str | None = None
    metadata: dict[str, Any] | None = None


@router.post("/boards/{board_id}/test-methods", status_code=201)
def add_board_test_method(
    board_id: str, body: BoardTestMethodCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Add test method to a board."""
    try:
        return board_service.add_board_test_method(
            board_id=board_id,
            method_name=body.method_name,
            description=body.description,
            test_command=body.test_command,
            requires_tools=body.requires_tools,
            timeout_seconds=body.timeout_seconds,
            is_default=body.is_default,
            board_revision_id=body.board_revision_id,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Board Probe Profiles

class BoardProbeProfileCreate(BaseModel):
    probe_method: str
    match_pattern: str | None = None
    match_fields: dict[str, Any] | None = None
    confidence: int = 100
    board_revision_id: str | None = None
    metadata: dict[str, Any] | None = None


@router.post("/boards/{board_id}/probe-profiles", status_code=201)
def add_board_probe_profile(
    board_id: str, body: BoardProbeProfileCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Add probe profile to a board."""
    try:
        return board_service.add_board_probe_profile(
            board_id=board_id,
            probe_method=body.probe_method,
            match_pattern=body.match_pattern,
            match_fields=body.match_fields,
            confidence=body.confidence,
            board_revision_id=body.board_revision_id,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc

# Made with Bob
