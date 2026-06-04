"""Worker poll loop built on pyjobkit's SQLBackend (M4/M5).

``WorkerLoop`` is a synchronous wrapper that:
1. Accepts callable handlers (sync functions) registered per job kind.
2. Runs an *async* poll loop inside a freshly-created event loop so the
   underlying pyjobkit ``SQLBackend`` can be used without any sync/async
   bridging issues.
3. Handles M5 capability routing: jobs whose required tags are not a
   subset of the worker's tags are skipped automatically.

Usage::

    loop = WorkerLoop(backend, "my-worker", ["source.fetch"],
                      worker_tags=["arch:aarch64"])
    loop.register("source.fetch", my_handler_fn)
    loop.run(stop_event)  # blocks until stop_event is set
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC
from typing import Any

from osfabricum.queue.backend import (
    OSF_REQUIRED_TAGS_KEY,
    JobBackend,
    JobView,
    _async_db_url,
)

HandlerFn = Callable[[JobView], None]


class WorkerLoop:
    """Single-threaded job poll loop backed by pyjobkit's ``SQLBackend``.

    Each handler is a plain synchronous callable that receives a
    :class:`~osfabricum.queue.backend.JobView` and may raise an exception
    to signal failure.

    The loop is **not** re-entrant: call :meth:`run` exactly once per
    ``WorkerLoop`` instance.
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
        self._worker_tags: list[str] = worker_tags or []
        self._poll_interval_s = poll_interval_s
        self._lease_ttl_s = lease_ttl_s
        self._handlers: dict[str, HandlerFn] = {}

    def register(self, kind: str, fn: HandlerFn) -> None:
        """Register a handler for *kind*.  Replaces any previous handler."""
        self._handlers[kind] = fn

    def run(self, stop: threading.Event | None = None) -> None:
        """Poll until *stop* is set.

        Creates a dedicated ``asyncio`` event loop for this invocation so
        the underlying pyjobkit async engine can operate without
        cross-loop interference.
        """
        stop = stop or threading.Event()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_run(stop))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    async def _async_run(self, stop: threading.Event) -> None:
        """Internal async poll loop."""
        from pyjobkit.backends.sql.backend import SQLBackend as _PjkSQLBackend
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        engine = create_async_engine(_async_db_url(self._backend._db_url), poolclass=NullPool)
        sql_backend = _PjkSQLBackend(engine, lease_ttl_s=self._lease_ttl_s)

        try:
            while not stop.is_set():
                await _do_expire_leases(sql_backend)
                job = await _do_claim_next(
                    sql_backend,
                    self._kinds,
                    self._worker_hostname,
                    set(self._worker_tags),
                    self._lease_ttl_s,
                )

                if job is None:
                    await asyncio.sleep(self._poll_interval_s)
                    continue

                handler = self._handlers.get(job.kind)
                if handler is None:
                    await _do_fail(
                        sql_backend,
                        job.id,
                        f"no handler registered for kind {job.kind!r}",
                    )
                    continue

                try:
                    handler(job)
                    await _do_complete(sql_backend, job.id)
                except Exception as exc:  # noqa: BLE001
                    await _do_fail(sql_backend, job.id, repr(exc))
        finally:
            await engine.dispose()


# ---------------------------------------------------------------------------
# Standalone async helpers (shared by WorkerLoop and can be reused elsewhere)
# ---------------------------------------------------------------------------


async def _do_expire_leases(sql_backend: Any) -> int:  # noqa: ANN401
    """Requeue or fail jobs whose lease has timed out."""
    from datetime import datetime

    from pyjobkit.backends.sql.schema import JobTasks
    from sqlalchemy import select, update

    now = datetime.now(UTC)

    async with sql_backend.sessionmaker() as session:
        expired = (
            (
                await session.execute(
                    select(JobTasks)
                    .where(JobTasks.c.status == "running")
                    .where(JobTasks.c.lease_until.is_not(None))
                    .where(JobTasks.c.lease_until <= now)
                )
            )
            .mappings()
            .all()
        )

        count = 0
        for row in expired:
            attempts = int(row["attempts"])
            max_attempts = int(row["max_attempts"])
            if attempts < max_attempts:
                await session.execute(
                    update(JobTasks)
                    .where(JobTasks.c.id == str(row["id"]))
                    .where(JobTasks.c.version == row["version"])
                    .values(
                        status="queued",
                        leased_by=None,
                        lease_until=None,
                        scheduled_for=now,
                        result={"error": "lease expired"},
                        version=JobTasks.c.version + 1,
                    )
                )
            else:
                await session.execute(
                    update(JobTasks)
                    .where(JobTasks.c.id == str(row["id"]))
                    .where(JobTasks.c.version == row["version"])
                    .values(
                        status="failed",
                        finished_at=now,
                        result={"error": "lease expired: max attempts exhausted"},
                        version=JobTasks.c.version + 1,
                    )
                )
            count += 1
        await session.commit()
        return count


async def _do_claim_next(
    sql_backend: Any,  # noqa: ANN401
    kinds: list[str],
    worker_hostname: str,
    tags_set: set[str],
    lease_ttl_s: int,
) -> JobView | None:
    """Claim the next matching job, respecting M5 required-tag routing."""
    from datetime import datetime, timedelta

    from pyjobkit.backends.sql.schema import JobTasks
    from sqlalchemy import select, update

    now = datetime.now(UTC)

    async with sql_backend.sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(JobTasks)
                    .where(JobTasks.c.status == "queued")
                    .where(JobTasks.c.kind.in_(kinds))
                    .where(JobTasks.c.scheduled_for <= now)
                    .order_by(JobTasks.c.priority.asc(), JobTasks.c.created_at.asc())
                )
            )
            .mappings()
            .all()
        )

        target: dict[str, Any] | None = None
        for row in rows:
            row_dict = dict(row)
            req = set((row_dict.get("payload") or {}).get(OSF_REQUIRED_TAGS_KEY) or [])
            if req.issubset(tags_set):
                target = row_dict
                break

        if target is None:
            return None

        from osfabricum.queue.backend import OSF_LEASE_TTL_KEY

        payload_ttl = (target.get("payload") or {}).get(OSF_LEASE_TTL_KEY)
        effective_ttl = int(payload_ttl) if payload_ttl is not None else lease_ttl_s
        lease_until = now + timedelta(seconds=effective_ttl)
        result = await session.execute(
            update(JobTasks)
            .where(JobTasks.c.id == str(target["id"]))
            .where(JobTasks.c.version == target["version"])
            .where(JobTasks.c.status == "queued")
            .values(
                status="running",
                leased_by=worker_hostname,
                lease_until=lease_until,
                started_at=now,
                attempts=JobTasks.c.attempts + 1,
                version=JobTasks.c.version + 1,
            )
        )
        await session.commit()

        if not result.rowcount:
            return None

        payload = target.get("payload") or {}
        return JobView(
            id=str(target["id"]),
            kind=str(target["kind"]),
            status="running",
            worker_hostname=worker_hostname,
            attempt=int(target.get("attempts", 0)) + 1,
            max_attempts=int(target.get("max_attempts", 3)),
            required_tags_json=list(payload.get(OSF_REQUIRED_TAGS_KEY) or []),
            payload=dict(payload),
        )


async def _do_complete(sql_backend: Any, job_id: str) -> None:  # noqa: ANN401
    """Mark *job_id* as SUCCEEDED."""
    from uuid import UUID

    await sql_backend.succeed(UUID(job_id), {})


async def _do_fail(  # noqa: ANN401
    sql_backend: Any,
    job_id: str,
    error: str,
) -> None:
    """Mark *job_id* as failed or requeue it if retries remain."""
    from datetime import datetime

    from pyjobkit.backends.sql.schema import JobTasks
    from sqlalchemy import select, update

    from osfabricum.queue.backend import OSF_RETRY_POLICY_KEY

    now = datetime.now(UTC)

    async with sql_backend.sessionmaker() as session:
        row = (
            (await session.execute(select(JobTasks).where(JobTasks.c.id == job_id)))
            .mappings()
            .first()
        )

        if row is None:
            return

        attempts = int(row["attempts"])
        max_attempts = int(row["max_attempts"])
        retry_policy = str((row.get("payload") or {}).get(OSF_RETRY_POLICY_KEY, "fixed"))

        if attempts < max_attempts and retry_policy != "manual":
            await session.execute(
                update(JobTasks)
                .where(JobTasks.c.id == job_id)
                .values(
                    status="queued",
                    leased_by=None,
                    lease_until=None,
                    scheduled_for=now,
                    result={"error": error},
                    version=JobTasks.c.version + 1,
                )
            )
        else:
            await session.execute(
                update(JobTasks)
                .where(JobTasks.c.id == job_id)
                .values(
                    status="failed",
                    finished_at=now,
                    result={"error": error},
                    version=JobTasks.c.version + 1,
                )
            )
        await session.commit()
