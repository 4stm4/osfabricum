"""SQL-backed job queue backend."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from osfabricum.db.models import Job
from osfabricum.db.session import sync_session


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class JobBackend:
    """Thread-safe SQL job queue.

    Uses an optimistic-lock pattern for claim operations: a SELECT followed by
    an UPDATE WHERE status='queued' — if another worker wins the race, the
    claim returns None and the caller retries on the next poll cycle.

    A threading.Lock serialises claim attempts within a single process, which
    avoids redundant contention on SQLite (which serialises writes anyway).
    """

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url = db_url
        self._claim_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Enqueueing
    # ------------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        max_attempts: int = 3,
        lease_ttl_s: int = 60,
        retry_policy: str = "fixed",
    ) -> str:
        """Create a QUEUED job and return its id."""
        with sync_session(self._db_url) as session:
            job = Job(
                kind=kind,
                payload_json=payload,
                max_attempts=max_attempts,
                lease_ttl_s=lease_ttl_s,
                retry_policy=retry_policy,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job.id

    # ------------------------------------------------------------------
    # Claiming
    # ------------------------------------------------------------------

    def claim_next(
        self,
        kinds: list[str],
        worker_hostname: str,
        *,
        lease_ttl_s: int | None = None,
    ) -> Job | None:
        """Atomically claim the oldest QUEUED job whose kind is in *kinds*.

        Returns the claimed ``Job`` instance (detached from the session) or
        ``None`` if no matching job is available.
        """
        with self._claim_lock:
            with sync_session(self._db_url) as session:
                stmt = (
                    select(Job)
                    .where(Job.status == "queued", Job.kind.in_(kinds))
                    .order_by(Job.created_at)
                    .limit(1)
                )
                job = session.scalar(stmt)
                if job is None:
                    return None
                now = _now()
                result = session.execute(
                    update(Job)
                    .where(Job.id == job.id, Job.status == "queued")
                    .values(
                        status="claimed",
                        worker_hostname=worker_hostname,
                        claimed_at=now,
                        lease_ttl_s=(lease_ttl_s if lease_ttl_s is not None else job.lease_ttl_s),
                        updated_at=now,
                    )
                )
                session.commit()
                if result.rowcount == 0:  # type: ignore[attr-defined]
                    return None
                # Fetch fresh state after update
                claimed = session.get(Job, job.id)
                if claimed is not None:
                    session.expunge(claimed)
                return claimed

    # ------------------------------------------------------------------
    # Completing / failing
    # ------------------------------------------------------------------

    def complete(self, job_id: str) -> None:
        """Mark *job_id* as COMPLETED."""
        with sync_session(self._db_url) as session:
            session.execute(
                update(Job).where(Job.id == job_id).values(status="completed", updated_at=_now())
            )
            session.commit()

    def fail(self, job_id: str, error: str = "") -> None:
        """Mark *job_id* as failed.

        If the job has remaining attempts and its retry policy allows it, the
        job is re-queued with attempt incremented.  Otherwise it transitions to
        FAILED.
        """
        with sync_session(self._db_url) as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            now = _now()
            if job.attempt < job.max_attempts and job.retry_policy != "manual":
                session.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(
                        status="queued",
                        attempt=job.attempt + 1,
                        worker_hostname=None,
                        claimed_at=None,
                        error_message=error,
                        updated_at=now,
                    )
                )
            else:
                session.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(status="failed", error_message=error, updated_at=now)
                )
            session.commit()

    # ------------------------------------------------------------------
    # Lease expiry
    # ------------------------------------------------------------------

    def expire_leases(self) -> int:
        """Requeue jobs whose claimed lease has timed out.

        Returns the number of jobs affected.
        """
        with sync_session(self._db_url) as session:
            now = _now()
            claimed = session.scalars(
                select(Job).where(Job.status == "claimed", Job.claimed_at.is_not(None))
            ).all()
            count = 0
            for job in claimed:
                if job.claimed_at is None:
                    continue
                deadline = job.claimed_at + timedelta(seconds=job.lease_ttl_s)
                if now < deadline:
                    continue
                if job.attempt < job.max_attempts:
                    session.execute(
                        update(Job)
                        .where(Job.id == job.id)
                        .values(
                            status="queued",
                            attempt=job.attempt + 1,
                            worker_hostname=None,
                            claimed_at=None,
                            error_message="lease expired",
                            updated_at=now,
                        )
                    )
                else:
                    session.execute(
                        update(Job)
                        .where(Job.id == job.id)
                        .values(
                            status="failed",
                            error_message="lease expired: max attempts exhausted",
                            updated_at=now,
                        )
                    )
                count += 1
            session.commit()
            return count

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def queue_depth(self) -> dict[str, int]:
        """Return ``{kind: count}`` for all QUEUED jobs."""
        with sync_session(self._db_url) as session:
            rows = session.execute(
                select(Job.kind, func.count(Job.id))
                .where(Job.status == "queued")
                .group_by(Job.kind)
            ).all()
        return {kind: count for kind, count in rows}

    def status_counts(self) -> dict[str, int]:
        """Return ``{status: count}`` across all jobs."""
        with sync_session(self._db_url) as session:
            rows = session.execute(
                select(Job.status, func.count(Job.id)).group_by(Job.status)
            ).all()
        return {status: count for status, count in rows}
