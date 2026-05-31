"""WorkerLoop handler for ``toolchain.fetch`` jobs (M6).

The handler factory :func:`make_toolchain_fetch_handler` binds the
``store_root`` and ``db_url`` deployment parameters and returns a plain
synchronous :data:`~osfabricum.queue.worker.HandlerFn` that can be
registered with :class:`~osfabricum.queue.worker.WorkerLoop`.

Expected job payload::

    {
        "toolchain_id": "<name or UUID of the Toolchain record>"
    }

``store_root`` and ``db_url`` are bound at worker startup time, not
stored in the job payload, because they are deployment concerns (path on
the worker host, credentials) rather than job-level data.
"""

from __future__ import annotations

from pathlib import Path

from osfabricum.queue.backend import JobView
from osfabricum.queue.worker import HandlerFn
from osfabricum.toolchain.fetch import fetch_toolchain


def make_toolchain_fetch_handler(
    store_root: Path,
    db_url: str | None = None,
) -> HandlerFn:
    """Return a ``toolchain.fetch`` handler bound to *store_root* / *db_url*.

    Usage::

        loop = WorkerLoop(backend, hostname, ["toolchain.fetch"])
        loop.register(
            "toolchain.fetch",
            make_toolchain_fetch_handler(Path("/store"), db_url=settings.database.url),
        )
        loop.run()
    """

    def _handle(job: JobView) -> None:
        toolchain_id = str(job.payload.get("toolchain_id", ""))
        if not toolchain_id:
            raise ValueError("job payload missing 'toolchain_id'")
        fetch_toolchain(toolchain_id, store_root, db_url)

    return _handle
