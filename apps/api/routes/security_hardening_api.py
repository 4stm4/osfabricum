"""Security / Hardening Designer API (M47).

    GET  /v1/security-mac-kinds
    GET  /v1/security-profiles
    POST /v1/security-profiles
    GET  /v1/security-profiles/{profile_id}
    PATCH /v1/security-profiles/{profile_id}
    POST /v1/security-profiles/{profile_id}/sysctl
    POST /v1/security-profiles/{profile_id}/mac-rules
    POST /v1/security-profiles/{profile_id}/pam-rules
    POST /v1/security-profiles/{profile_id}/capabilities
    POST /v1/security-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import hardening as hd
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["security"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# MAC kinds
# ---------------------------------------------------------------------------


@router.get("/v1/security-mac-kinds")
def list_mac_kinds(req: Request) -> list[dict]:
    return hd.list_mac_kinds(db_url=_db(req))


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class CreateProfileBody(BaseModel):
    name: str
    distribution_id: str | None = None
    mac_policy: str = "none"
    description: str = ""


class UpdateProfileBody(BaseModel):
    name: str | None = None
    mac_policy: str | None = None
    description: str | None = None


@router.get("/v1/security-profiles")
def list_security_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    return hd.list_security_profiles(distribution_id=distribution_id, db_url=_db(req))


@router.post("/v1/security-profiles")
def create_security_profile(
    _auth: WriteAuthDep, req: Request, body: CreateProfileBody
) -> dict:
    try:
        return hd.create_security_profile(
            body.name,
            distribution_id=body.distribution_id,
            mac_policy=body.mac_policy,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/v1/security-profiles/{profile_id}")
def get_security_profile(profile_id: str, req: Request) -> dict:
    try:
        return hd.get_security_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/v1/security-profiles/{profile_id}")
def update_security_profile(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: UpdateProfileBody
) -> dict:
    try:
        return hd.update_security_profile(
            profile_id,
            name=body.name,
            mac_policy=body.mac_policy,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Sysctl settings
# ---------------------------------------------------------------------------


class SetSysctlBody(BaseModel):
    key: str
    value: str
    description: str = ""


@router.post("/v1/security-profiles/{profile_id}/sysctl")
def set_sysctl(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: SetSysctlBody
) -> dict:
    try:
        return hd.set_sysctl(
            profile_id,
            body.key,
            body.value,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# MAC rules
# ---------------------------------------------------------------------------


class AddMacRuleBody(BaseModel):
    subject: str
    rule_text: str
    is_enforcing: bool = True
    priority: int = 100
    comment: str | None = None


@router.post("/v1/security-profiles/{profile_id}/mac-rules")
def add_mac_rule(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: AddMacRuleBody
) -> dict:
    try:
        return hd.add_mac_rule(
            profile_id,
            body.subject,
            body.rule_text,
            is_enforcing=body.is_enforcing,
            priority=body.priority,
            comment=body.comment,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# PAM rules
# ---------------------------------------------------------------------------


class AddPamRuleBody(BaseModel):
    service: str
    module_type: str
    control_flag: str
    module_path: str
    module_args: str | None = None
    priority: int = 100


@router.post("/v1/security-profiles/{profile_id}/pam-rules")
def add_pam_rule(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: AddPamRuleBody
) -> dict:
    try:
        return hd.add_pam_rule(
            profile_id,
            body.service,
            body.module_type,
            body.control_flag,
            body.module_path,
            module_args=body.module_args,
            priority=body.priority,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Capability grants
# ---------------------------------------------------------------------------


class SetCapabilityBody(BaseModel):
    executable: str
    add_caps: str | None = None
    drop_caps: str | None = None
    no_new_privs: bool = False
    description: str = ""


@router.post("/v1/security-profiles/{profile_id}/capabilities")
def set_capability_grant(
    profile_id: str, _auth: WriteAuthDep, req: Request, body: SetCapabilityBody
) -> dict:
    try:
        return hd.set_capability_grant(
            profile_id,
            body.executable,
            add_caps=body.add_caps,
            drop_caps=body.drop_caps,
            no_new_privs=body.no_new_privs,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/security-profiles/{profile_id}/render")
def render_security_config(profile_id: str, _auth: WriteAuthDep, req: Request) -> dict:
    try:
        return hd.render_security_config(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
