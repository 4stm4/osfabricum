"""Sync façade around pyjobkit Engine + SQL backend (M4/M5).

Architecture:
  - All public methods are **synchronous** and use ``asyncio.run()`` internally.
  - Persistence uses pyjobkit's ``SQLBackend`` → ``job_tasks`` table.
  - M5 required-tag routing: tags are stored in the job payload under the
    ``__osf_required_tags`` key and checked in ``claim_next`` before claiming.
  - Retry policy "manual" is stored in payload under ``__osf_retry_policy``
    and causes ``fail()`` to mark the job FAILED regardless of attempt count.
  - ``NullPool`` is used so the async SQLAlchemy engine is safe to share
    across separate ``asyncio.run()`` invocations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.pool import NullPool

# Payload keys for OSFabricum extensions stored inside pyjobkit's JSON payload
OSF_REQUIRED_TAGS_KEY = "__osf_required_tags"
OSF_RETRY_POLICY_KEY = "__osf_retry_policy"
OSF_LEASE_TTL_KEY = "__osf_lease_ttl_s"


def _async_db_url(db_url: str) -> str:
    """Return an async-driver URL (adds +aiosqlite for plain SQLite URLs)."""
    if "://" not in db_url:
        return db_url
    if db_url.startswith("sqlite:///") and "+aiosqlite" not in db_url:
        return db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return db_url


@dataclass
class JobView:
    """Lightweight view of a pyjobkit ``job_tasks`` row after claiming.

    Mimics the attribute API of the old ``Job`` ORM model so existing
    code and tests that reference ``job.id``, ``job.kind``, etc. keep
    working without changes.
    """

    id: str
    kind: str
    status: str
    worker_hostname: str | None
    attempt: int  # = ``attempts`` column value after the claim increment
    max_attempts: int
    required_tags_json: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


class JobBackend:
    """Thread-safe sync job queue backed by pyjobkit's SQLBackend.

    Each public method spins up a fresh ``asyncio`` event loop via
    ``asyncio.run()``; the underlying engine uses ``NullPool`` so no
    connections are shared across loop boundaries.

    M5 capability routing
    ---------------------
    Jobs may carry a list of *required tags* in their payload
    (``__osf_required_tags``).  ``claim_next`` only returns a job when the
    worker's ``worker_tags`` are a **superset** of the job's required tags.
    """

    def __init__(self, db_url: str | None = None) -> None:
        if db_url is None:
            from osfabricum.config import load_settings

            db_url = load_settings().database.url
        self._db_url: str = db_url

        from pyjobkit.backends.sql.backend import SQLBackend as _PjkSQLBackend
        from sqlalchemy.ext.asyncio import create_async_engine

        self._async_engine = create_async_engine(_async_db_url(db_url), poolclass=NullPool)
        self._sql_backend = _PjkSQLBackend(self._async_engine, lease_ttl_s=60)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, coro: Any) -> Any:  # noqa: ANN401
        return asyncio.run(coro)

    # ------------------------------------------------------------------
    # Enqueueing
    # ------------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        required_tags: list[str] | None = None,
        max_attempts: int = 3,
        lease_ttl_s: int = 60,  # stored as backend default; per-job not in pyjobkit
        retry_policy: str = "fixed",
    ) -> str:
        """Create a QUEUED job and return its id (string-form UUID)."""
        full_payload: dict[str, Any] = dict(payload or {})
        if required_tags:
            full_payload[OSF_REQUIRED_TAGS_KEY] = required_tags
        if retry_policy != "fixed":
            full_payload[OSF_RETRY_POLICY_KEY] = retry_policy
        if lease_ttl_s != 60:
            full_payload[OSF_LEASE_TTL_KEY] = lease_ttl_s

        async def _do() -> UUID:
            return await self._sql_backend.enqueue(
                kind=kind,
                payload=full_payload,
                max_attempts=max_attempts,
            )

        return str(self._run(_do()))

    # ------------------------------------------------------------------
    # Claiming  (M5 required-tag subset check lives here)
    # ------------------------------------------------------------------

    def claim_next(
        self,
        kinds: list[str],
        worker_hostname: str,
        *,
        worker_tags: list[str] | None = None,
        lease_ttl_s: int | None = None,
    ) -> JobView | None:
        """Claim the oldest QUEUED job whose required tags the worker satisfies.

        Returns a :class:`JobView` or ``None`` if no matching job is available.
        """
        return cast(
            "JobView | None",
            self._run(
                self._async_claim_next(
                    kinds,
                    worker_hostname,
                    set(worker_tags or []),
                    lease_ttl_s or self._sql_backend.lease_ttl_s,
                )
            ),
        )

    async def _async_claim_next(
        self,
        kinds: list[str],
        worker_hostname: str,
        tags_set: set[str],
        lease_ttl_s: int,
    ) -> JobView | None:
        from pyjobkit.backends.sql.schema import JobTasks

        now = datetime.now(UTC)

        async with self._sql_backend.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(JobTasks)
                    .where(JobTasks.c.status == "queued")
                    .where(JobTasks.c.kind.in_(kinds))
                    .where(JobTasks.c.scheduled_for <= now)
                    .order_by(JobTasks.c.priority.asc(), JobTasks.c.created_at.asc())
                )
            ).mappings().all()

            target: dict[str, Any] | None = None
            for row in rows:
                row_dict = dict(row)
                req = set((row_dict.get("payload") or {}).get(OSF_REQUIRED_TAGS_KEY) or [])
                if req.issubset(tags_set):
                    target = row_dict
                    break

            if target is None:
                return None

            # Per-job lease TTL takes precedence over the caller's default
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

            if result.rowcount == 0:  # type: ignore[attr-defined]
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

    # ------------------------------------------------------------------
    # Completing / failing
    # ------------------------------------------------------------------

    def complete(self, job_id: str) -> None:
        """Mark *job_id* as SUCCEEDED."""
        self._run(self._sql_backend.succeed(UUID(job_id), {}))

    def fail(self, job_id: str, error: str = "") -> None:
        """Mark *job_id* as failed or requeue it if retries remain.

        Requeue conditions: ``attempts < max_attempts`` AND
        ``retry_policy != "manual"``.
        """
        self._run(self._async_fail(job_id, error))

    async def _async_fail(self, job_id: str, error: str) -> None:
        from pyjobkit.backends.sql.schema import JobTasks

        now = datetime.now(UTC)

        async with self._sql_backend.sessionmaker() as session:
            row = (
                await session.execute(select(JobTasks).where(JobTasks.c.id == job_id))
            ).mappings().first()

            if row is None:
                return

            attempts: int = int(row["attempts"])
            max_attempts: int = int(row["max_attempts"])
            retry_policy: str = str((row.get("payload") or {}).get(OSF_RETRY_POLICY_KEY, "fixed"))

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

    # ------------------------------------------------------------------
    # Lease expiry
    # ------------------------------------------------------------------

    def expire_leases(self) -> int:
        """Requeue or fail jobs whose lease has expired.

        Jobs with remaining attempts are re-queued; jobs that have
        exhausted all attempts are marked FAILED.

        Returns the number of jobs affected.
        """
        return cast(int, self._run(self._async_expire_leases()))

    async def _async_expire_leases(self) -> int:
        from pyjobkit.backends.sql.schema import JobTasks

        now = datetime.now(UTC)

        async with self._sql_backend.sessionmaker() as session:
            expired = (
                await session.execute(
                    select(JobTasks)
                    .where(JobTasks.c.status == "running")
                    .where(JobTasks.c.lease_until.is_not(None))
                    .where(JobTasks.c.lease_until <= now)
                )
            ).mappings().all()

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

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def queue_depth(self) -> dict[str, int]:
        """Return ``{kind: count}`` for all QUEUED jobs."""
        return cast("dict[str, int]", self._run(self._async_queue_depth()))

    async def _async_queue_depth(self) -> dict[str, int]:
        from pyjobkit.backends.sql.schema import JobTasks

        async with self._sql_backend.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(JobTasks.c.kind, func.count(JobTasks.c.id))
                    .where(JobTasks.c.status == "queued")
                    .group_by(JobTasks.c.kind)
                )
            ).all()
        return {kind: int(count) for kind, count in rows}

    def status_counts(self) -> dict[str, int]:
        """Return ``{status: count}`` across all jobs."""
        return cast("dict[str, int]", self._run(self._async_status_counts()))

    async def _async_status_counts(self) -> dict[str, int]:
        from pyjobkit.backends.sql.schema import JobTasks

        async with self._sql_backend.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(JobTasks.c.status, func.count(JobTasks.c.id)).group_by(
                        JobTasks.c.status
                    )
                )
            ).all()
        return {status: int(count) for status, count in rows}
