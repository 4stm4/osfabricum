"""Package Workspace / Package Manager API (M35).

    GET  /v1/package-kinds | /v1/package-layers
    POST /v1/packages/cache          — record a cache entry
    POST /v1/packages/cache/lookup   — look up a key identity (explains a miss)
    POST /v1/packages/cache/explain  — diff two key-component maps
    GET  /v1/packages/cache          — cache stats
    GET/POST /v1/package-groups ; POST /{id}/members
    GET/POST /v1/package-sets ; POST /{id}/members ; POST /{id}/resolve
    POST /v1/packages/{id}/classify ; GET/POST /v1/packages/{id}/variants
    GET/POST /v1/package-locks | /v1/package-feeds ; POST /{id}/index
    POST /v1/package-promotions

Reads and pure computations (lookup / explain / resolve) are public; mutations
require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from osfabricum import packageworkspace as pw
from osfabricum.security.auth_policy import WriteAuthDep

router = APIRouter(prefix="/v1", tags=["package-workspace"])


def _db(req: Request) -> str | None:
    try:
        return req.app.state.settings.database.url  # type: ignore[no-any-return]
    except AttributeError:
        return None


def _guard(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=404 if "not found" in str(exc) else 400, detail=str(exc))


# --- request models ---


class CacheKeyRequest(BaseModel):
    name: str
    version: str
    arch: str
    kind: str = "system"
    source_hash: str = ""
    recipe_hash: str = ""
    feature_hash: str = ""
    libc: str = ""
    toolchain_hash: str = ""
    abi_hash: str = ""
    kernel_release: str | None = None
    kernel_config_hash: str | None = None
    artifact_id: str | None = None

    def key_kwargs(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("artifact_id", None)
        return data


class ExplainRequest(BaseModel):
    a: dict[str, Any]
    b: dict[str, Any]


class GroupRequest(BaseModel):
    name: str
    distribution_id: str | None = None
    description: str | None = None


class GroupMemberRequest(BaseModel):
    package_id: str
    version_constraint: str | None = None


class SetRequest(BaseModel):
    name: str
    distribution_id: str | None = None
    description: str | None = None


class SetMemberRequest(BaseModel):
    member_kind: str
    group_id: str | None = None
    package_id: str | None = None


class ResolveRequest(BaseModel):
    profile_id: str | None = None


class ClassifyRequest(BaseModel):
    kind: str
    layer: str


class LockRequest(BaseModel):
    package_name: str
    version: str
    cache_key: str | None = None
    reason: str | None = None


class FeedRequest(BaseModel):
    name: str
    channel: str = "stable"
    description: str | None = None


class FeedIndexRequest(BaseModel):
    package_name: str
    version: str
    cache_key: str | None = None


class PromotionRequest(BaseModel):
    package_name: str
    version: str
    to_channel: str
    from_channel: str | None = None


class VariantRequest(BaseModel):
    name: str
    feature_hash: str | None = None
    description: str | None = None


# --- taxonomy ---


@router.get("/package-kinds")
def list_kinds(request: Request) -> list[dict[str, Any]]:
    return pw.list_kinds(db_url=_db(request))


@router.get("/package-layers")
def list_layers(request: Request) -> list[dict[str, Any]]:
    return pw.list_layers(db_url=_db(request))


@router.post("/packages/{package_id}/classify")
def classify(
    package_id: str, body: ClassifyRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.classify_package(
            package_id, kind=body.kind, layer=body.layer, db_url=_db(request)
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- cache ---


@router.get("/packages/cache")
def cache_stats(request: Request) -> dict[str, Any]:
    return pw.cache_stats(db_url=_db(request))


@router.post("/packages/cache", status_code=201)
def record_cache(
    body: CacheKeyRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.record_cache_entry(
            artifact_id=body.artifact_id, db_url=_db(request), **body.key_kwargs()
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/packages/cache/lookup")
def lookup_cache(body: CacheKeyRequest, request: Request) -> dict[str, Any]:
    try:
        return pw.lookup_cache(db_url=_db(request), **body.key_kwargs())
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/packages/cache/explain")
def explain_cache(body: ExplainRequest) -> dict[str, Any]:
    return pw.explain_cache(body.a, body.b)


# --- groups ---


@router.get("/package-groups")
def list_groups(request: Request) -> list[dict[str, Any]]:
    return pw.list_groups(db_url=_db(request))


@router.post("/package-groups", status_code=201)
def create_group(
    body: GroupRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.create_group(
            body.name,
            distribution_id=body.distribution_id,
            description=body.description,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/package-groups/{group_id}/members", status_code=201)
def add_group_member(
    group_id: str, body: GroupMemberRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.add_to_group(
            group_id,
            body.package_id,
            version_constraint=body.version_constraint,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- sets ---


@router.get("/package-sets")
def list_sets(request: Request) -> list[dict[str, Any]]:
    return pw.list_sets(db_url=_db(request))


@router.post("/package-sets", status_code=201)
def create_set(body: SetRequest, request: Request, _auth: WriteAuthDep = None) -> dict[str, Any]:
    try:
        return pw.create_set(
            body.name,
            distribution_id=body.distribution_id,
            description=body.description,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/package-sets/{set_id}/members", status_code=201)
def add_set_member(
    set_id: str, body: SetMemberRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.add_to_set(
            set_id,
            member_kind=body.member_kind,
            group_id=body.group_id,
            package_id=body.package_id,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/package-sets/{set_id}/resolve")
def resolve_set(set_id: str, body: ResolveRequest, request: Request) -> dict[str, Any]:
    try:
        return pw.resolve_set(set_id, profile_id=body.profile_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


# --- variants ---


@router.get("/packages/{package_id}/variants")
def list_variants(package_id: str, request: Request) -> list[dict[str, Any]]:
    return pw.list_variants(package_id, db_url=_db(request))


@router.post("/packages/{package_id}/variants", status_code=201)
def create_variant(
    package_id: str, body: VariantRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.create_variant(
            package_id,
            body.name,
            feature_hash=body.feature_hash,
            description=body.description,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- locks ---


@router.get("/package-locks")
def list_locks(request: Request) -> list[dict[str, Any]]:
    return pw.list_locks(db_url=_db(request))


@router.post("/package-locks", status_code=201)
def create_lock(body: LockRequest, request: Request, _auth: WriteAuthDep = None) -> dict[str, Any]:
    try:
        return pw.create_lock(
            body.package_name,
            body.version,
            cache_key=body.cache_key,
            reason=body.reason,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- feeds ---


@router.get("/package-feeds")
def list_feeds(request: Request) -> list[dict[str, Any]]:
    return pw.list_feeds(db_url=_db(request))


@router.post("/package-feeds", status_code=201)
def create_feed(body: FeedRequest, request: Request, _auth: WriteAuthDep = None) -> dict[str, Any]:
    try:
        return pw.create_feed(
            body.name, channel=body.channel, description=body.description, db_url=_db(request)
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/package-feeds/{feed_id}/index", status_code=201)
def add_feed_index(
    feed_id: str, body: FeedIndexRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.add_feed_index(
            feed_id, body.package_name, body.version, cache_key=body.cache_key, db_url=_db(request)
        )
    except ValueError as exc:
        raise _guard(exc) from exc


# --- promotions ---


@router.post("/package-promotions", status_code=201)
def promote(body: PromotionRequest, request: Request, _auth: WriteAuthDep = None) -> dict[str, Any]:
    return pw.promote(
        body.package_name,
        body.version,
        body.to_channel,
        from_channel=body.from_channel,
        db_url=_db(request),
    )
