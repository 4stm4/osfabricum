"""Service / Init / Device Manager Designer API (M46).

    GET  /v1/init-system-kinds
    GET  /v1/service-profiles
    POST /v1/service-profiles
    GET  /v1/service-profiles/{profile_id}
    PATCH /v1/service-profiles/{profile_id}
    POST /v1/service-profiles/{profile_id}/entries
    POST /v1/service-profiles/{profile_id}/device-rules
    POST /v1/service-profiles/{profile_id}/unit-overrides
    POST /v1/service-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import services as svc
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["services"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# Init system kinds
# ---------------------------------------------------------------------------


@router.get("/v1/init-system-kinds")
def list_init_system_kinds(req: Request) -> list[dict]:
    return svc.list_init_system_kinds(db_url=_db(req))


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class CreateProfileBody(BaseModel):
    name: str
    distribution_id: str | None = None
    init_system: str = "systemd"
    description: str = ""


class UpdateProfileBody(BaseModel):
    name: str | None = None
    init_system: str | None = None
    description: str | None = None


@router.get("/v1/service-profiles")
def list_service_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    return svc.list_service_profiles(distribution_id=distribution_id, db_url=_db(req))


@router.post("/v1/service-profiles")
def create_service_profile(_auth: WriteAuthDep, req: Request, body: CreateProfileBody) -> dict:
    try:
        return svc.create_service_profile(
            body.name,
            distribution_id=body.distribution_id,
            init_system=body.init_system,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/service-profiles/{profile_id}")
def get_service_profile(profile_id: str, req: Request) -> dict:
    try:
        return svc.get_service_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/v1/service-profiles/{profile_id}")
def update_service_profile(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: UpdateProfileBody
) -> dict:
    try:
        return svc.update_service_profile(
            profile_id,
            name=body.name,
            init_system=body.init_system,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Service entries
# ---------------------------------------------------------------------------


class AddEntryBody(BaseModel):
    name: str
    unit_type: str = "service"
    description: str = ""
    exec_start: str | None = None
    exec_stop: str | None = None
    exec_pre_start: str | None = None
    restart_policy: str = "no"
    wanted_by: str = "multi-user.target"
    after: str | None = None
    requires: str | None = None
    environment: str | None = None
    working_directory: str | None = None
    run_user: str | None = None
    run_group: str | None = None
    is_enabled: bool = True
    is_masked: bool = False
    priority: int = 100


@router.post("/v1/service-profiles/{profile_id}/entries")
def add_service_entry(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: AddEntryBody
) -> dict:
    try:
        return svc.add_service_entry(
            profile_id,
            body.name,
            unit_type=body.unit_type,
            description=body.description,
            exec_start=body.exec_start,
            exec_stop=body.exec_stop,
            exec_pre_start=body.exec_pre_start,
            restart_policy=body.restart_policy,
            wanted_by=body.wanted_by,
            after=body.after,
            requires=body.requires,
            environment=body.environment,
            working_directory=body.working_directory,
            run_user=body.run_user,
            run_group=body.run_group,
            is_enabled=body.is_enabled,
            is_masked=body.is_masked,
            priority=body.priority,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Device rules
# ---------------------------------------------------------------------------


class AddDeviceRuleBody(BaseModel):
    subsystem: str | None = None
    kernel_pattern: str | None = None
    attr_filter: str | None = None
    udev_action: str = "add"
    symlink: str | None = None
    mode: str | None = None
    owner: str | None = None
    group_name: str | None = None
    run_command: str | None = None
    priority: int = 90
    comment: str | None = None


@router.post("/v1/service-profiles/{profile_id}/device-rules")
def add_device_rule(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: AddDeviceRuleBody
) -> dict:
    try:
        return svc.add_device_rule(
            profile_id,
            subsystem=body.subsystem,
            kernel_pattern=body.kernel_pattern,
            attr_filter=body.attr_filter,
            udev_action=body.udev_action,
            symlink=body.symlink,
            mode=body.mode,
            owner=body.owner,
            group_name=body.group_name,
            run_command=body.run_command,
            priority=body.priority,
            comment=body.comment,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Unit overrides
# ---------------------------------------------------------------------------


class SetUnitOverrideBody(BaseModel):
    unit_name: str
    override_content: str
    section: str = "Service"


@router.post("/v1/service-profiles/{profile_id}/unit-overrides")
def set_unit_override(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: SetUnitOverrideBody
) -> dict:
    try:
        return svc.set_unit_override(
            profile_id,
            body.unit_name,
            body.override_content,
            section=body.section,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/service-profiles/{profile_id}/render")
def render_service_config(profile_id: str, _auth: WriteAuthDep, req: Request) -> dict:
    try:
        return svc.render_service_config(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
