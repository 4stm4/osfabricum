"""Entry point for ``osfabricum-worker``.

M1 provides a runnable skeleton: the worker registers its declared kinds/tags,
logs ``waiting for jobs`` and idles until interrupted. pyjobkit queue polling
is wired in M4.
"""

from __future__ import annotations

import signal
import threading
from pathlib import Path
from typing import Annotated

import typer

from osfabricum.config import load_settings
from osfabricum.logging import configure_logging, get_logger

log = get_logger("osfabricum.worker")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def run_worker(
    config: Path | None = None,
    worker_id: str = "worker-local-01",
    kinds: str = "",
    tags: str = "",
    poll_interval_s: float = 5.0,
    stop: threading.Event | None = None,
) -> None:
    settings = load_settings(config)
    configure_logging(settings.telemetry.log_format, "info")
    fields = {
        "worker_id": worker_id,
        "kinds": _split_csv(kinds),
        "tags": _split_csv(tags),
    }
    log.info("worker starting", extra={"fields": fields})
    log.info("waiting for jobs", extra={"fields": fields})

    stop = stop or threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    while not stop.is_set():
        # M4: claim and execute jobs from the pyjobkit queue here.
        stop.wait(timeout=poll_interval_s)

    log.info("worker stopped", extra={"fields": {"worker_id": worker_id}})


def _cli(
    config: Annotated[Path | None, typer.Option("--config", help="Config file path")] = None,
    worker_id: Annotated[
        str, typer.Option("--worker-id", help="Worker identity")
    ] = "worker-local-01",
    kinds: Annotated[str, typer.Option("--kinds", help="Comma-separated job kinds")] = "",
    tags: Annotated[str, typer.Option("--tags", help="Comma-separated routing tags")] = "",
) -> None:
    run_worker(config=config, worker_id=worker_id, kinds=kinds, tags=tags)


def main() -> None:
    typer.run(_cli)


if __name__ == "__main__":
    main()
