"""WorkerLoop handler for ``kernel.build`` jobs (M10).

Expected job payload::

    {
        "kernel_id":    "<name or UUID of the Kernel record>",
        "board_name":   "<board name, optional>",
        "store_root":   "<absolute path>",
        "jobs":         4
    }

``store_root`` and ``db_url`` are bound at worker startup via the factory
:func:`make_kernel_build_handler`.
"""

from __future__ import annotations

from pathlib import Path

from osfabricum.kernel.build import build_kernel
from osfabricum.queue.backend import JobView
from osfabricum.queue.worker import HandlerFn


def make_kernel_build_handler(
    store_root: Path,
    db_url: str | None = None,
) -> HandlerFn:
    """Return a ``kernel.build`` handler bound to *store_root* / *db_url*.

    Usage::

        loop = WorkerLoop(backend, hostname, ["kernel.build"])
        loop.register(
            "kernel.build",
            make_kernel_build_handler(Path("/store"), db_url=settings.database.url),
        )
        loop.run()
    """

    def _handle(job: JobView) -> None:
        kernel_id = str(job.payload.get("kernel_id", ""))
        if not kernel_id:
            raise ValueError("job payload missing 'kernel_id'")
        board_name = str(job.payload.get("board_name", "")) or None
        jobs = int(job.payload.get("jobs", 1))
        result = build_kernel(
            kernel_id,
            store_root=store_root,
            board_name=board_name,
            db_url=db_url,
            jobs=jobs,
        )
        if not result.success:
            raise RuntimeError(
                f"kernel build failed: {result.error}\nwork_dir: {result.work_dir}"
            )

    return _handle
