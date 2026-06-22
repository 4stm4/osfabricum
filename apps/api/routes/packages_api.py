"""Package Workspace / Package Manager API (M35/M36/M37).

    GET  /v1/packages                 — list all packages + versions + cache status
    POST /v1/packages/ingest-url      — download .ofpkg from URL and ingest into cache
    POST /v1/packages/upload          — upload .ofpkg file and ingest into cache
    GET  /v1/package-kinds | /v1/package-layers
    POST /v1/packages/cache          — record a cache entry
    POST /v1/packages/cache/lookup   — look up a key identity (explains a miss)
    POST /v1/packages/cache/explain  — diff two key-component maps
    GET  /v1/packages/cache          — cache stats
    GET/POST /v1/package-groups ; POST /{id}/members
    GET/POST /v1/package-sets ; POST /{id}/members ; POST /{id}/resolve
    POST /v1/packages/{id}/classify ; GET/POST /v1/packages/{id}/variants
    GET/POST /v1/package-locks
    GET/POST /v1/package-feeds ; POST /{id}/index ; POST /{id}/scope ; POST /{id}/publish
    GET /v1/package-feeds/{id}
    POST /v1/package-promotions

Reads and pure computations (lookup / explain / resolve) are public; mutations
require auth (WriteAuthDep, G-24).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
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


class FeedScopeRequest(BaseModel):
    distribution: str | None = None
    arch: str | None = None
    libc: str | None = None
    kernel_release: str | None = None


class VariantRequest(BaseModel):
    name: str
    feature_hash: str | None = None
    description: str | None = None


class FeatureValueRequest(BaseModel):
    value: str
    implied_deps: list[str] | None = None
    description: str | None = None


class FeatureRequest(BaseModel):
    name: str
    type: str
    default: str | None = None
    values: list[FeatureValueRequest] | None = None
    description: str | None = None


class VariantResolveRequest(BaseModel):
    package_id: str
    requested: dict[str, str] = {}


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


# --- features (M36) ---


@router.get("/packages/{package_id}/features")
def list_features(package_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        return pw.list_features(package_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/packages/{package_id}/features", status_code=201)
def define_feature(
    package_id: str, body: FeatureRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    values = [v.model_dump() for v in body.values] if body.values else None
    try:
        return pw.define_feature(
            package_id,
            body.name,
            body.type,
            default=body.default,
            values=values,
            description=body.description,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/package-variants/resolve")
def resolve_variant(body: VariantResolveRequest, request: Request) -> dict[str, Any]:
    try:
        return pw.resolve_variant(body.package_id, body.requested, db_url=_db(request))
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


@router.get("/package-feeds/{feed_id}")
def get_feed(feed_id: str, request: Request) -> dict[str, Any]:
    try:
        return pw.get_feed(feed_id, db_url=_db(request))
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/package-feeds/{feed_id}/scope", status_code=201)
def scope_feed(
    feed_id: str, body: FeedScopeRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    try:
        return pw.scope_feed(
            feed_id,
            distribution=body.distribution,
            arch=body.arch,
            libc=body.libc,
            kernel_release=body.kernel_release,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise _guard(exc) from exc


@router.post("/package-feeds/{feed_id}/publish", status_code=201)
def publish_feed(feed_id: str, request: Request, _auth: WriteAuthDep = None) -> dict[str, Any]:
    try:
        return pw.publish_feed(feed_id, db_url=_db(request))
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


# ---------------------------------------------------------------------------
# Package list + cache ingestion
# ---------------------------------------------------------------------------


@router.get("/packages")
def list_packages(request: Request) -> list[dict[str, Any]]:
    """List all packages with their versions and cache (artifact) status."""
    from sqlalchemy import select  # noqa: PLC0415

    from osfabricum.db.models import Architecture, Artifact, Package, PackageVersion  # noqa: PLC0415
    from osfabricum.db.session import sync_session  # noqa: PLC0415

    db_url = _db(request)
    with sync_session(db_url) as s:
        packages = s.scalars(select(Package).order_by(Package.name)).all()
        arch_names: dict[str, str] = {
            a.id: a.name for a in s.scalars(select(Architecture)).all()
        }
        versions = s.scalars(select(PackageVersion)).all()
        artifact_ids = [pv.artifact_id for pv in versions if pv.artifact_id]
        artifacts: dict[str, Artifact] = {}
        if artifact_ids:
            for art in s.scalars(select(Artifact).where(Artifact.id.in_(artifact_ids))).all():
                artifacts[art.id] = art

        pkg_versions: dict[str, list[dict]] = {}
        for pv in versions:
            art = artifacts.get(pv.artifact_id) if pv.artifact_id else None
            pkg_versions.setdefault(pv.package_id, []).append({
                "id": pv.id,
                "version": pv.version,
                "arch": arch_names.get(pv.arch_id, pv.arch_id),
                "cached": pv.artifact_id is not None,
                "artifact_id": pv.artifact_id,
                "size_bytes": art.size_bytes if art else None,
                "cached_at": art.created_at.isoformat() if art and art.created_at else None,
            })

        result = []
        for pkg in packages:
            result.append({
                "id": pkg.id,
                "name": pkg.name,
                "kind": pkg.kind,
                "layer": pkg.layer,
                "versions": pkg_versions.get(pkg.id, []),
            })
        return result


class IngestUrlRequest(BaseModel):
    url: str
    package_version_id: str | None = None


def _ingest_ofpkg_bytes(
    data: bytes,
    store_root_str: str | None,
    db_url: str | None,
    package_version_id: str | None = None,
) -> dict[str, Any]:
    """Verify, ingest and link a .ofpkg payload. Returns artifact info dict."""
    import io  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    import uuid  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from sqlalchemy import select as _sel  # noqa: PLC0415
    from sqlalchemy import update as _upd  # noqa: PLC0415

    from osfabricum.db.models import Architecture, Package, PackageVersion  # noqa: PLC0415
    from osfabricum.db.session import sync_session  # noqa: PLC0415
    from osfabricum.packaging.installer import verify_ofpkg  # noqa: PLC0415
    from osfabricum.store.ingest import ingest_blob  # noqa: PLC0415

    store_root = Path(store_root_str) if store_root_str else Path("/store")

    with tempfile.NamedTemporaryFile(suffix=".ofpkg", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        manifest = verify_ofpkg(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    name = manifest["name"]
    version = manifest["version"]
    arch_name = manifest["arch"]

    store_key = f"packages/{name}/{version}/{arch_name}/{name}-{version}-{arch_name}.ofpkg"
    artifact = ingest_blob(
        data,
        store_root=store_root,
        store_key=store_key,
        kind="package",
        name=name,
        version=version,
        arch=arch_name,
        media_type="application/zip",
        db_url=db_url,
    )

    # Link to PackageVersion: use provided id or find/create the row
    with sync_session(db_url) as s:
        arch_row = s.scalar(_sel(Architecture).where(Architecture.name == arch_name))
        if arch_row is None:
            raise ValueError(f"Architecture {arch_name!r} not found in DB — add it first")

        if package_version_id:
            pv = s.get(PackageVersion, package_version_id)
            if pv is None:
                raise ValueError(f"PackageVersion {package_version_id!r} not found")
        else:
            # Find or create Package + PackageVersion
            pkg = s.scalar(_sel(Package).where(Package.name == name))
            if pkg is None:
                pkg = Package(id=str(uuid.uuid4()), name=name, package_type="native")
                s.add(pkg)
                s.flush()
            pv = s.scalar(
                _sel(PackageVersion).where(
                    PackageVersion.package_id == pkg.id,
                    PackageVersion.version == version,
                    PackageVersion.arch_id == arch_row.id,
                )
            )
            if pv is None:
                pv = PackageVersion(
                    id=str(uuid.uuid4()),
                    package_id=pkg.id,
                    version=version,
                    arch_id=arch_row.id,
                    status="cached",
                )
                s.add(pv)
                s.flush()
            package_version_id = pv.id

        s.execute(
            _upd(PackageVersion)
            .where(PackageVersion.id == package_version_id)
            .values(artifact_id=artifact.id, status="cached")
        )
        s.commit()

    return {
        "artifact_id": artifact.id,
        "package_version_id": package_version_id,
        "name": name,
        "version": version,
        "arch": arch_name,
        "size_bytes": artifact.size_bytes,
        "blob_sha256": artifact.blob_sha256,
    }


@router.post("/packages/ingest-url", status_code=201)
def ingest_from_url(
    body: IngestUrlRequest, request: Request, _auth: WriteAuthDep = None
) -> dict[str, Any]:
    """Download a .ofpkg from a URL, verify it, and add it to the cache."""
    import urllib.request  # noqa: PLC0415

    try:
        with urllib.request.urlopen(body.url, timeout=120) as resp:  # noqa: S310
            data = resp.read()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Download failed: {exc}") from exc

    try:
        settings = getattr(request.app.state, "settings", None)
        store_root_str = settings.store.root if settings else None
        return _ingest_ofpkg_bytes(
            data,
            store_root_str=store_root_str,
            db_url=_db(request),
            package_version_id=body.package_version_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/packages/upload", status_code=201)
async def ingest_upload(
    request: Request,
    file: UploadFile = File(...),
    _auth: WriteAuthDep = None,
) -> dict[str, Any]:
    """Upload a .ofpkg file, verify it, and add it to the cache."""
    if not (file.filename or "").endswith(".ofpkg"):
        raise HTTPException(status_code=422, detail="File must be a .ofpkg archive")

    data = await file.read()
    try:
        settings = getattr(request.app.state, "settings", None)
        store_root_str = settings.store.root if settings else None
        return _ingest_ofpkg_bytes(
            data,
            store_root_str=store_root_str,
            db_url=_db(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
