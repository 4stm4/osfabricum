"""OSFabricum Orchestrator API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.routes.artifacts_api import router as artifacts_router
from apps.api.routes.builds import router as builds_router
from apps.api.routes.catalog import router as catalog_router
from apps.api.routes.distributions_api import router as distributions_router
from apps.api.routes.drafts_api import router as drafts_router
from apps.api.routes.model_api import router as model_router
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

        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app


app = create_app()
