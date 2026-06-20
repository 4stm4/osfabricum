"""Entry point for ``osfabricum-worker``.

M4: worker registers itself in the ``workers`` table, sends periodic
heartbeats, and runs the SQL job-queue poll loop (JobBackend + WorkerLoop).
"""

from __future__ import annotations

import os
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from osfabricum.db.models import Worker
from osfabricum.db.session import sync_session
from osfabricum.logging import configure_logging, get_logger
from osfabricum.queue import JobBackend, WorkerLoop  # noqa: F401 – re-exported
from osfabricum.settings import load_settings

log = get_logger("osfabricum.worker")

_HEARTBEAT_PERIOD_S = 10.0


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _register_worker(
    hostname: str,
    kinds: list[str],
    tags: list[str],
    db_url: str,
    capabilities: dict[str, object] | None = None,
) -> None:
    """Upsert the worker row in the ``workers`` table."""
    pid = os.getpid()
    try:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Worker).where(Worker.hostname == hostname))
            now = _now_utc()
            if existing is None:
                session.add(
                    Worker(
                        hostname=hostname,
                        kinds_json=kinds,
                        tags_json=tags,
                        capabilities_json=capabilities,
                        last_seen_at=now,
                        pid=pid,
                    )
                )
            else:
                session.execute(
                    update(Worker)
                    .where(Worker.hostname == hostname)
                    .values(
                        kinds_json=kinds,
                        tags_json=tags,
                        capabilities_json=capabilities,
                        last_seen_at=now,
                        pid=pid,
                    )
                )
            session.commit()
    except OperationalError:
        log.warning("worker registration skipped: DB schema not initialised")


def _heartbeat_loop(hostname: str, db_url: str, stop: threading.Event) -> None:
    while not stop.wait(timeout=_HEARTBEAT_PERIOD_S):
        try:
            with sync_session(db_url) as session:
                session.execute(
                    update(Worker)
                    .where(Worker.hostname == hostname)
                    .values(last_seen_at=_now_utc())
                )
                session.commit()
        except Exception:  # noqa: BLE001
            pass  # heartbeat is best-effort


def run_worker(
    config: Path | None = None,
    worker_id: str = "worker-local-01",
    kinds: str = "",
    tags: str = "",
    poll_interval_s: float = 5.0,
    stop: threading.Event | None = None,
    db_url: str | None = None,
) -> None:
    settings = load_settings(config)
    configure_logging(settings.telemetry.log_format, "info")

    kind_list = _split_csv(kinds)
    tag_list = _split_csv(tags)
    fields = {"worker_id": worker_id, "kinds": kind_list, "tags": tag_list}
    log.info("worker starting", extra={"fields": fields})
    log.info("waiting for jobs", extra={"fields": fields})

    stop_event = stop or threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())

    effective_db_url = db_url or settings.database.url

    if db_url is not None:
        _register_worker(worker_id, kind_list, tag_list, effective_db_url)
        hb_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(worker_id, effective_db_url, stop_event),
            daemon=True,
        )
        hb_thread.start()

    backend = JobBackend(effective_db_url if db_url is not None else None)
    loop = WorkerLoop(
        backend,
        worker_id,
        kind_list or ["*"],
        worker_tags=tag_list,
        poll_interval_s=poll_interval_s,
        lease_ttl_s=60,
    )

    # M29: this worker can execute queued builds (build.run jobs).
    from osfabricum.orchestrator import register_build_handler  # noqa: PLC0415

    register_build_handler(loop, db_url=effective_db_url, store_root=settings.store.root)

    loop.run(stop_event)

    log.info("worker stopped", extra={"fields": {"worker_id": worker_id}})


def _cli(
    config: Annotated[Path | None, typer.Option("--config", help="Config file path")] = None,
    worker_id: Annotated[
        str, typer.Option("--worker-id", help="Worker identity")
    ] = "worker-local-01",
    kinds: Annotated[str, typer.Option("--kinds", help="Comma-separated job kinds")] = "",
    tags: Annotated[str, typer.Option("--tags", help="Comma-separated routing tags")] = "",
    db_url: Annotated[str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL")] = None,
) -> None:
    run_worker(config=config, worker_id=worker_id, kinds=kinds, tags=tags, db_url=db_url)


def main() -> None:
    typer.run(_cli)


if __name__ == "__main__":
    main()
