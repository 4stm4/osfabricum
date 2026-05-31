"""Worker poll loop that claims and executes jobs from JobBackend."""

from __future__ import annotations

import threading
from collections.abc import Callable

from osfabricum.db.models import Job
from osfabricum.queue.backend import JobBackend

HandlerFn = Callable[[Job], None]


class WorkerLoop:
    """Single-threaded job poll loop.

    Handlers are registered by job kind.  On each iteration the loop:
    1. Expires stale leases.
    2. Tries to claim the next available job whose required tags are a subset
       of this worker's *worker_tags* (M5 capability routing).
    3. Executes the registered handler (or fails the job if no handler).
    4. Marks the job completed or failed based on the outcome.

    Pass a pre-set ``threading.Event`` as *stop* to run the loop for exactly
    one (or zero) iterations in tests.
    """

    def __init__(
        self,
        backend: JobBackend,
        worker_hostname: str,
        kinds: list[str],
        *,
        worker_tags: list[str] | None = None,
        poll_interval_s: float = 1.0,
        lease_ttl_s: int = 60,
    ) -> None:
        self._backend = backend
        self._worker_hostname = worker_hostname
        self._kinds = kinds
        self._worker_tags = worker_tags or []
        self._poll_interval_s = poll_interval_s
        self._lease_ttl_s = lease_ttl_s
        self._handlers: dict[str, HandlerFn] = {}

    def register(self, kind: str, fn: HandlerFn) -> None:
        """Register a handler for *kind*.  Replaces any previous handler."""
        self._handlers[kind] = fn

    def run(self, stop: threading.Event | None = None) -> None:
        """Poll until *stop* is set."""
        stop = stop or threading.Event()
        while not stop.is_set():
            self._backend.expire_leases()
            job = self._backend.claim_next(
                self._kinds,
                self._worker_hostname,
                worker_tags=self._worker_tags,
                lease_ttl_s=self._lease_ttl_s,
            )
            if job is None:
                stop.wait(timeout=self._poll_interval_s)
                continue
            handler = self._handlers.get(job.kind)
            if handler is None:
                self._backend.fail(job.id, f"no handler registered for kind {job.kind!r}")
                continue
            try:
                handler(job)
                self._backend.complete(job.id)
            except Exception as exc:  # noqa: BLE001
                self._backend.fail(job.id, repr(exc))
