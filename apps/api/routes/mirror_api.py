"""M51 — Cache / Mirror / Offline designer API."""

from __future__ import annotations

from fastapi import APIRouter, Request

from osfabricum import mirror
from osfabricum.db.session import sync_session
from osfabricum.security.auth import WriteAuthDep

router = APIRouter(prefix="/v1", tags=["mirror"])


def _db(req: Request) -> str | None:
    return req.app.state.settings.database.url


# ---------------------------------------------------------------------------
# Cache policy kinds (read-only)
# ---------------------------------------------------------------------------


@router.get("/cache-policy-kinds")
def list_policy_kinds(req: Request) -> list[dict]:
    with sync_session(_db(req)) as s:
        kinds = mirror.list_cache_policy_kinds(s)
    return [
        {
            "kind": k.kind,
            "label": k.label,
            "description": k.description,
            "display_order": k.display_order,
        }
        for k in kinds
    ]


# ---------------------------------------------------------------------------
# Mirror profiles
# ---------------------------------------------------------------------------


@router.get("/mirror-profiles")
def list_profiles(req: Request, distribution_id: str | None = None) -> list[dict]:
    with sync_session(_db(req)) as s:
        profiles = mirror.list_mirror_profiles(s, distribution_id)
    return [_profile_dict(p) for p in profiles]


@router.post("/mirror-profiles", dependencies=[WriteAuthDep])
def create_profile(req: Request, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = mirror.create_mirror_profile(
                s,
                name=body["name"],
                distribution_id=body.get("distribution_id"),
                description=body.get("description", ""),
                offline_mode=body.get("offline_mode", False),
                max_cache_size_mb=body.get("max_cache_size_mb"),
                cache_ttl_days=body.get("cache_ttl_days", 7),
            )
            s.commit()
            return _profile_dict(p)
        except (ValueError, KeyError) as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/mirror-profiles/{profile_id}")
def get_profile(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = mirror.get_mirror_profile(s, profile_id)
            return _profile_dict(p)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/mirror-profiles/{profile_id}", dependencies=[WriteAuthDep])
def update_profile(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = mirror.update_mirror_profile(s, profile_id, **body)
            s.commit()
            return _profile_dict(p)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Mirror endpoints
# ---------------------------------------------------------------------------


@router.get("/mirror-profiles/{profile_id}/endpoints")
def list_endpoints(req: Request, profile_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            eps = mirror.list_mirror_endpoints(s, profile_id)
            return [_endpoint_dict(e) for e in eps]
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/mirror-profiles/{profile_id}/endpoints",
    dependencies=[WriteAuthDep],
)
def add_endpoint(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            ep = mirror.add_mirror_endpoint(
                s,
                profile_id,
                url=body["url"],
                priority=body.get("priority", 0),
                is_default=body.get("is_default", False),
                requires_auth=body.get("requires_auth", False),
                auth_token_id=body.get("auth_token_id"),
            )
            s.commit()
            return _endpoint_dict(ep)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Cache rules
# ---------------------------------------------------------------------------


@router.get("/mirror-profiles/{profile_id}/cache-rules")
def list_rules(req: Request, profile_id: str) -> list[dict]:
    with sync_session(_db(req)) as s:
        try:
            rules = mirror.list_cache_rules(s, profile_id)
            return [_rule_dict(r) for r in rules]
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/mirror-profiles/{profile_id}/cache-rules",
    dependencies=[WriteAuthDep],
)
def add_rule(req: Request, profile_id: str, body: dict) -> dict:
    with sync_session(_db(req)) as s:
        try:
            rule = mirror.add_cache_rule(
                s,
                profile_id,
                source_pattern=body["source_pattern"],
                cache_policy=body.get("cache_policy", "prefer"),
                priority=body.get("priority", 0),
            )
            s.commit()
            return _rule_dict(rule)
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/mirror-profiles/{profile_id}/render", dependencies=[WriteAuthDep])
def render(req: Request, profile_id: str) -> dict:
    with sync_session(_db(req)) as s:
        try:
            p = mirror.render_mirror_config(s, profile_id)
            s.commit()
            return {
                "id": p.id,
                "content_hash": p.content_hash,
                "rendered_mirror_config": p.rendered_mirror_config,
                "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
            }
        except KeyError as exc:
            from fastapi import HTTPException  # noqa: PLC0415
            raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_dict(p: object) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "distribution_id": p.distribution_id,
        "description": p.description,
        "offline_mode": p.offline_mode,
        "max_cache_size_mb": p.max_cache_size_mb,
        "cache_ttl_days": p.cache_ttl_days,
        "content_hash": p.content_hash,
        "rendered_at": p.rendered_at.isoformat() if p.rendered_at else None,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _endpoint_dict(e: object) -> dict:
    return {
        "id": e.id,
        "profile_id": e.profile_id,
        "url": e.url,
        "priority": e.priority,
        "is_default": e.is_default,
        "requires_auth": e.requires_auth,
        "auth_token_id": e.auth_token_id,
    }


def _rule_dict(r: object) -> dict:
    return {
        "id": r.id,
        "profile_id": r.profile_id,
        "source_pattern": r.source_pattern,
        "cache_policy": r.cache_policy,
        "priority": r.priority,
    }
