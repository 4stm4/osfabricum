"""OSFabricum Orchestrator API.

M1 provides the application skeleton: liveness, readiness, and a metrics
placeholder. Real readiness checks (DB, queue, store) and Prometheus metrics
are wired in later milestones (M4/M20).
"""

from __future__ import annotations

from fastapi import FastAPI, Response

from osfabricum import __version__
from osfabricum.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="OSFabricum API", version=__version__)
    app.state.settings = settings

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, object]:
        # M1 stub: real checks (db/queue/store) land in M4.
        return {"status": "ok", "checks": {"db": "skipped", "queue": "skipped"}}

    @app.get("/metrics")
    def metrics() -> Response:
        body = f'# OSFabricum metrics placeholder\nosf_build_info{{version="{__version__}"}} 1\n'
        return Response(content=body, media_type="text/plain; version=0.0.4")

    return app


app = create_app()
