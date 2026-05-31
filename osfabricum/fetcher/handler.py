"""WorkerLoop handler for ``source.fetch`` jobs (M7).

Expected job payload::

    {
        "source_id": "<URI, UUID, or metadata name of the Source record>"
    }

``store_root`` and ``db_url`` are bound at worker startup time via the
factory :func:`make_source_fetch_handler`.
"""

from __future__ import annotations

from pathlib import Path

from osfabricum.fetcher.fetch import fetch_source
from osfabricum.queue.backend import JobView
from osfabricum.queue.worker import HandlerFn


def make_source_fetch_handler(
    store_root: Path,
    db_url: str | None = None,
) -> HandlerFn:
    """Return a ``source.fetch`` handler bound to *store_root* / *db_url*.

    Usage::

        loop = WorkerLoop(backend, hostname, ["source.fetch"])
        loop.register(
            "source.fetch",
            make_source_fetch_handler(Path("/store"), db_url=settings.database.url),
        )
        loop.run()
    """

    def _handle(job: JobView) -> None:
        source_id = str(job.payload.get("source_id", ""))
        if not source_id:
            raise ValueError("job payload missing 'source_id'")
        fetch_source(source_id, store_root, db_url)

    return _handle
