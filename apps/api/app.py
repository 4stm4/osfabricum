"""OSFabricum Orchestrator API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.routes.appcatalog_api import router as appcatalog_router
from apps.api.routes.desktopint_api import router as desktopint_router
from apps.api.routes.theme_api import router as theme_router
from apps.api.routes.network_api import router as network_router
from apps.api.routes.compliance_api import router as compliance_router
from apps.api.routes.security_hardening_api import router as security_router
from apps.api.routes.update_ota_api import router as update_ota_router
from apps.api.routes.sdk_api import router as sdk_router
from apps.api.routes.mirror_api import router as mirror_router
from apps.api.routes.probe_api import router as probe_router
from apps.api.routes.layers_api import router as layers_router
from apps.api.routes.overrides_api import router as overrides_router
from apps.api.routes.services_api import router as services_router
from apps.api.routes.users_api import router as users_router
from apps.api.routes.artifacts_api import router as artifacts_router
from apps.api.routes.boards_api import router as boards_router
from apps.api.routes.bootchain_api import router as bootchain_router
from apps.api.routes.branding_api import router as branding_router
from apps.api.routes.builds import router as builds_router
from apps.api.routes.catalog import router as catalog_router
from apps.api.routes.distributions_api import router as distributions_router
from apps.api.routes.drafts_api import router as drafts_router
from apps.api.routes.graphical_api import router as graphical_router
from apps.api.routes.imagedesign_api import router as imagedesign_router
from apps.api.routes.initramfs_api import router as initramfs_router
from apps.api.routes.kerneldesign_api import router as kerneldesign_router
from apps.api.routes.model_api import router as model_router
from apps.api.routes.packagepolicy_api import router as packagepolicy_router
from apps.api.routes.packages_api import router as packages_router
from apps.api.routes.plan_api import prefetch_router
from apps.api.routes.plan_api import router as plan_router
from apps.api.routes.profiles_api import router as profiles_router
from apps.api.routes.workers_api import router as workers_router
from osfabricum import __version__
from osfabricum.queue.backend import JobBackend
from osfabricum.security.auth import TokenAuthMiddleware
from osfabricum.settings import Settings, load_settings

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="OSFabricum API", version=__version__)
    app.state.settings = settings

    # M14: token auth middleware (disabled by default)
    if settings.auth.enabled:
        app.add_middleware(TokenAuthMiddleware, settings=settings)

    # M19: build history API
    app.include_router(builds_router)
    # M20: catalog / artifacts / workers / plan API
    app.include_router(catalog_router)
    app.include_router(artifacts_router)
    app.include_router(workers_router)
    app.include_router(plan_router)
    # M29: plan write API + prefetch
    app.include_router(prefetch_router)
    # M25: universal OS builder model (distribution classes)
    app.include_router(model_router)
    # M26: distribution designer (write API)
    app.include_router(distributions_router)
    # M27: profile designer (write API)
    app.include_router(profiles_router)
    # M28: build wizard drafts
    app.include_router(drafts_router)
    # M30: board/BSP designer (write API)
    app.include_router(boards_router)
    # M31: boot chain designer (write API)
    app.include_router(bootchain_router)
    # M32: initramfs designer (write API)
    app.include_router(initramfs_router)
    # M33: kernel / driver designer (write API)
    app.include_router(kerneldesign_router)
    # M34: filesystem / image recipe designer (write API)
    app.include_router(imagedesign_router)
    # M35: package workspace / package manager (write API)
    app.include_router(packages_router)
    # M38: runtime package policy (write API)
    app.include_router(packagepolicy_router)
    # M39: branding / identity designer
    app.include_router(branding_router)
    # M40: graphical shell designer
    app.include_router(graphical_router)
    # M41: application catalog designer
    app.include_router(appcatalog_router)
    # M42: desktop integration designer
    app.include_router(desktopint_router)
    # M43: themes / icons / fonts designer
    app.include_router(theme_router)
    # M44: users / groups / credentials / secrets designer
    app.include_router(users_router)
    # M45: network designer
    app.include_router(network_router)
    # M46: service / init / device manager designer
    app.include_router(services_router)
    # M47: security / hardening designer
    app.include_router(security_router)
    # M48: license / SBOM / vuln / source compliance designer
    app.include_router(compliance_router)
    # M49: update / OTA / recovery designer
    app.include_router(update_ota_router)
    # M50: SDK / dev-shell export designer
    app.include_router(sdk_router)
    # M51: cache / mirror / offline designer
    app.include_router(mirror_router)
    # M53: hardware probe import
    app.include_router(probe_router)
    # M54: OS composition layers designer
    app.include_router(layers_router)
    # M55: override / masking engine
    app.include_router(overrides_router)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, object]:
        return {"status": "ok", "checks": {"db": "skipped", "queue": "skipped"}}

    @app.get("/metrics")
    def metrics() -> Response:
        lines = [
            f'osf_build_info{{version="{__version__}"}} 1',
        ]
        try:
            backend = JobBackend(settings.database.url)
            for kind, count in backend.queue_depth().items():
                lines.append(f'osf_job_queue_depth{{kind="{kind}"}} {count}')
        except Exception:  # noqa: BLE001
            lines.append("# osf_job_queue_depth unavailable: schema not ready")
        body = "\n".join(lines) + "\n"
        return Response(content=body, media_type="text/plain; version=0.0.4")

    @app.get("/internal/queue")
    def internal_queue() -> dict[str, object]:
        """Queue dashboard (admin only in production; unprotected in M4)."""
        try:
            backend = JobBackend(settings.database.url)
            return {
                "queue_depth": backend.queue_depth(),
                "status_counts": backend.status_counts(),
            }
        except Exception:  # noqa: BLE001
            return {"error": "database schema not ready"}

    # M20: Web UI dashboard (static, served at root)
    if _STATIC_DIR.exists():

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "index.html"))

        # M26: Distribution Designer page (client of the write API)
        @app.get("/distributions", include_in_schema=False)
        def distributions_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "distributions.html"))

        # M27: Profile Designer page (client of the write API)
        @app.get("/profiles", include_in_schema=False)
        def profiles_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "profiles.html"))

        # M28: Universal Build Wizard (client of the plan/build write API)
        @app.get("/build/new", include_in_schema=False)
        def build_wizard_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "build_new.html"))

        # M30: Board / BSP Designer page
        @app.get("/boards", include_in_schema=False)
        def boards_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "boards.html"))

        # M31: Boot Chain Designer page
        @app.get("/boot-chains", include_in_schema=False)
        def bootchain_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "bootchain.html"))

        # M32: Initramfs Designer page
        @app.get("/initramfs", include_in_schema=False)
        def initramfs_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "initramfs.html"))

        # M33: Kernel / Driver Designer page
        @app.get("/kernel-config", include_in_schema=False)
        def kernel_config_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "kernel.html"))

        # M34: Filesystem / Image Recipe Designer page
        @app.get("/image-recipes", include_in_schema=False)
        def image_recipes_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "image_recipes.html"))

        # M35: Package Workspace page
        @app.get("/packages", include_in_schema=False)
        def packages_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "packages.html"))

        # M39: Branding / Identity Designer page
        @app.get("/branding", include_in_schema=False)
        def branding_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "branding.html"))

        # M40: Graphical Shell Designer page
        @app.get("/graphical", include_in_schema=False)
        def graphical_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "graphical.html"))

        # M41: Application Catalog Designer page
        @app.get("/appcatalog", include_in_schema=False)
        def appcatalog_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "appcatalog.html"))

        # M42: Desktop Integration Designer page
        @app.get("/desktopint", include_in_schema=False)
        def desktopint_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "desktopint.html"))

        # M43: Themes / Icons / Fonts Designer page
        @app.get("/theme", include_in_schema=False)
        def theme_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "theme.html"))

        # M44: Users / Groups / Credentials / Secrets Designer page
        @app.get("/users", include_in_schema=False)
        def users_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "users.html"))

        # M45: Network Designer page
        @app.get("/network", include_in_schema=False)
        def network_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "network.html"))

        # M46: Service / Init / Device Manager Designer page
        @app.get("/services", include_in_schema=False)
        def services_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "services.html"))

        # M47: Security / Hardening Designer page
        @app.get("/security", include_in_schema=False)
        def security_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "security.html"))

        # M48: Compliance Designer page
        @app.get("/compliance", include_in_schema=False)
        def compliance_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "compliance.html"))

        # M49: Update / OTA / Recovery Designer page
        @app.get("/updates", include_in_schema=False)
        def updates_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "updates.html"))

        # M50: SDK / dev-shell export designer page
        @app.get("/sdk", include_in_schema=False)
        def sdk_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "sdk.html"))

        # M51: Cache / Mirror / Offline designer page
        @app.get("/mirror", include_in_schema=False)
        def mirror_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "mirror.html"))

        # M53: Hardware Probe import page
        @app.get("/probe", include_in_schema=False)
        def probe_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "probe.html"))

        # M54: OS Composition Layers designer page
        @app.get("/layers", include_in_schema=False)
        def layers_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "layers.html"))

        # M55: Override / Masking engine designer page
        @app.get("/overrides", include_in_schema=False)
        def overrides_page() -> FileResponse:
            return FileResponse(str(_STATIC_DIR / "overrides.html"))

        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app


app = create_app()
