"""Users / Groups / Credentials / Secrets Designer API (M44).

    GET  /v1/user-shell-kinds
    GET  /v1/user-profiles
    POST /v1/user-profiles
    GET  /v1/user-profiles/{profile_id}
    PATCH /v1/user-profiles/{profile_id}
    POST /v1/user-profiles/{profile_id}/groups
    POST /v1/user-profiles/{profile_id}/users
    POST /v1/user-profiles/{profile_id}/users/{user_id}/supplementary-groups
    POST /v1/user-profiles/{profile_id}/secrets
    POST /v1/user-profiles/{profile_id}/render

Reads are public; mutations require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import users as us
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(tags=["users"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# Shell kinds
# ---------------------------------------------------------------------------


@router.get("/v1/user-shell-kinds")
def list_shell_kinds(req: Request) -> list[dict]:
    return us.list_user_shell_kinds(db_url=_db(req))


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class CreateProfileBody(BaseModel):
    name: str
    distribution_id: str | None = None


class UpdateProfileBody(BaseModel):
    name: str | None = None


@router.get("/v1/user-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    return us.list_user_profiles(distribution_id, db_url=_db(req))


@router.post("/v1/user-profiles")
def create_profile(body: CreateProfileBody, req: Request, _: WriteAuthDep) -> dict:
    try:
        return us.create_user_profile(
            body.name, distribution_id=body.distribution_id, db_url=_db(req)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/user-profiles/{profile_id}")
def get_profile(profile_id: str, req: Request) -> dict:
    try:
        return us.get_user_profile(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/v1/user-profiles/{profile_id}")
def update_profile(
    profile_id: str, body: UpdateProfileBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return us.update_user_profile(profile_id, name=body.name, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


class AddGroupBody(BaseModel):
    name: str
    gid: int | None = None
    is_system: bool = False
    description: str = ""


@router.post("/v1/user-profiles/{profile_id}/groups")
def add_group(
    profile_id: str, body: AddGroupBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return us.add_os_group(
            profile_id,
            body.name,
            gid=body.gid,
            is_system=body.is_system,
            description=body.description,
            db_url=_db(req),
        )
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class AddUserBody(BaseModel):
    username: str
    uid: int | None = None
    primary_group: str = "users"
    home_dir: str | None = None
    shell: str = "/bin/bash"
    gecos: str = ""
    is_system: bool = False
    is_locked: bool = False
    password_hash: str | None = None


@router.post("/v1/user-profiles/{profile_id}/users")
def add_user(
    profile_id: str, body: AddUserBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return us.add_os_user(
            profile_id,
            body.username,
            uid=body.uid,
            primary_group=body.primary_group,
            home_dir=body.home_dir,
            shell=body.shell,
            gecos=body.gecos,
            is_system=body.is_system,
            is_locked=body.is_locked,
            password_hash=body.password_hash,
            db_url=_db(req),
        )
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Supplementary groups
# ---------------------------------------------------------------------------


class AddSuppGroupBody(BaseModel):
    group_name: str


@router.post("/v1/user-profiles/{profile_id}/users/{user_id}/supplementary-groups")
def add_supplementary_group(
    profile_id: str,
    user_id: str,
    body: AddSuppGroupBody,
    req: Request,
    _: WriteAuthDep,
) -> dict:
    try:
        return us.add_supplementary_group(
            user_id, body.group_name, db_url=_db(req)
        )
    except ValueError as exc:
        status = 409 if "already" in str(exc) else 404
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class AddSecretBody(BaseModel):
    name: str
    kind: str
    description: str = ""
    masked_value: str | None = None
    is_required: bool = True


@router.post("/v1/user-profiles/{profile_id}/secrets")
def add_secret(
    profile_id: str, body: AddSecretBody, req: Request, _: WriteAuthDep
) -> dict:
    try:
        return us.add_secret_variable(
            profile_id,
            body.name,
            body.kind,
            description=body.description,
            masked_value=body.masked_value,
            is_required=body.is_required,
            db_url=_db(req),
        )
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/v1/user-profiles/{profile_id}/render")
def render(profile_id: str, req: Request, _: WriteAuthDep) -> dict:
    try:
        return us.render_user_config(profile_id, db_url=_db(req))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
