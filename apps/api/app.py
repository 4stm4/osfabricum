"""OSFabricum Orchestrator API."""

from __future__ import annotations

from fastapi import FastAPI, Response

from osfabricum import __version__
from osfabricum.queue.backend import JobBackend
from osfabricum.security.auth import TokenAuthMiddleware
from osfabricum.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="OSFabricum API", version=__version__)
    app.state.settings = settings

    # M14: token auth middleware (disabled by default)
    if settings.auth.enabled:
        app.add_middleware(TokenAuthMiddleware, settings=settings)

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

    return app


app = create_app()
