"""Boot Chain API (M31).

    GET    /v1/boot-chains              — list boot chains
    POST   /v1/boot-chains              — create boot chain
    GET    /v1/boot-chains/{id}         — get boot chain with templates/files
    POST   /v1/boot-chains/{id}/templates — add template
    POST   /v1/boot-chains/{id}/files   — add file
    POST   /v1/boot-chains/{id}/bind    — bind to board/profile
    POST   /v1/boot-chains/{id}/render  — render boot files
    POST   /v1/boot-chains/{id}/validate — validate boot chain
    GET    /v1/boot-chain-bindings      — list bindings
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from osfabricum import bootchain as bootchain_service
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(prefix="/v1", tags=["boot-chains"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    status = 404 if "not found" in str(exc) else 400
    return HTTPException(status_code=status, detail=str(exc))


# Boot Chains

class BootChainCreate(BaseModel):
    name: str
    boot_scheme_id: str
    description: str | None = None
    metadata: dict[str, Any] | None = None


@router.get("/boot-chains")
def list_boot_chains(request: Request) -> list[dict[str, Any]]:
    """List all boot chains."""
    return bootchain_service.list_boot_chains(db_url=_db(request))


@router.post("/boot-chains", status_code=201)
def create_boot_chain(
    body: BootChainCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Create a new boot chain."""
    try:
        return bootchain_service.create_boot_chain(
            name=body.name,
            boot_scheme_id=body.boot_scheme_id,
            description=body.description,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/boot-chains/{boot_chain_id}")
def get_boot_chain(boot_chain_id: str, request: Request) -> dict[str, Any]:
    """Get boot chain with all templates and files."""
    try:
        return bootchain_service.get_boot_chain(boot_chain_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


# Templates

class BootChainTemplateCreate(BaseModel):
    template_type: str
    content: str
    variables: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@router.post("/boot-chains/{boot_chain_id}/templates", status_code=201)
def add_boot_chain_template(
    boot_chain_id: str, body: BootChainTemplateCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Add a template to a boot chain."""
    try:
        return bootchain_service.add_boot_chain_template(
            boot_chain_id=boot_chain_id,
            template_type=body.template_type,
            content=body.content,
            variables=body.variables,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Files

class BootChainFileCreate(BaseModel):
    filename: str
    placement: str
    content_template: str | None = None
    template_id: str | None = None
    required: bool = True
    permissions: str | None = None
    metadata: dict[str, Any] | None = None


@router.post("/boot-chains/{boot_chain_id}/files", status_code=201)
def add_boot_chain_file(
    boot_chain_id: str, body: BootChainFileCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Add a file to a boot chain."""
    try:
        return bootchain_service.add_boot_chain_file(
            boot_chain_id=boot_chain_id,
            filename=body.filename,
            placement=body.placement,
            content_template=body.content_template,
            template_id=body.template_id,
            required=body.required,
            permissions=body.permissions,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# Bindings

class BootChainBindingCreate(BaseModel):
    board_id: str | None = None
    profile_id: str | None = None
    is_default: bool = False
    priority: int = 100
    metadata: dict[str, Any] | None = None


@router.post("/boot-chains/{boot_chain_id}/bind", status_code=201)
def bind_boot_chain(
    boot_chain_id: str, body: BootChainBindingCreate, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Bind a boot chain to a board and/or profile."""
    try:
        return bootchain_service.bind_boot_chain(
            boot_chain_id=boot_chain_id,
            board_id=body.board_id,
            profile_id=body.profile_id,
            is_default=body.is_default,
            priority=body.priority,
            metadata=body.metadata,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.get("/boot-chain-bindings")
def list_boot_chain_bindings(
    request: Request,
    board_id: Annotated[str | None, Query()] = None,
    profile_id: Annotated[str | None, Query()] = None,
) -> list[dict[str, Any]]:
    """List boot chain bindings, optionally filtered by board/profile."""
    return bootchain_service.list_boot_chain_bindings(
        board_id=board_id,
        profile_id=profile_id,
        db_url=_db(request),
    )


# Render & Validate

class BootChainRenderRequest(BaseModel):
    variables: dict[str, Any]


@router.post("/boot-chains/{boot_chain_id}/render")
def render_boot_chain(
    boot_chain_id: str, body: BootChainRenderRequest, request: Request
) -> dict[str, Any]:
    """Render boot chain files with provided variables."""
    try:
        return bootchain_service.render_boot_chain(
            boot_chain_id=boot_chain_id,
            variables=body.variables,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


class BootChainValidateRequest(BaseModel):
    context: dict[str, Any]


@router.post("/boot-chains/{boot_chain_id}/validate")
def validate_boot_chain(
    boot_chain_id: str, body: BootChainValidateRequest, request: Request
) -> dict[str, Any]:
    """Validate that boot chain has all required components."""
    try:
        return bootchain_service.validate_boot_chain(
            boot_chain_id=boot_chain_id,
            context=body.context,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc

# Made with Bob
