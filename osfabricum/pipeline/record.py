"""Build record management (M18).

Functions for creating and updating ``Build``, ``BuildJob``, and
``BuildEvent`` rows in the database.  These are the primary audit trail
for every pipeline run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import Build, BuildEvent, BuildJob
from osfabricum.db.session import sync_session


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def create_build(
    distribution_id: str,
    profile_id: str,
    board_id: str,
    resolution_hash: str,
    *,
    db_url: str | None = None,
) -> str:
    """Insert a new ``Build`` row with status ``"running"`` and return its ID."""
    with sync_session(db_url) as session:
        build = Build(
            distribution_id=distribution_id,
            profile_id=profile_id,
            board_id=board_id,
            resolution_hash=resolution_hash,
            status="running",
        )
        session.add(build)
        session.commit()
        session.refresh(build)
        return build.id


def update_build_status(
    build_id: str,
    status: str,
    *,
    db_url: str | None = None,
) -> None:
    """Update ``Build.status`` to *status*."""
    with sync_session(db_url) as session:
        build: Build | None = session.scalar(select(Build).where(Build.id == build_id))
        if build is None:
            raise ValueError(f"build not found: {build_id!r}")
        build.status = status
        build.updated_at = _now()
        session.commit()


def get_build(build_id: str, *, db_url: str | None = None) -> Build | None:
    """Return the ``Build`` row for *build_id*, or ``None``."""
    with sync_session(db_url) as session:
        build = session.scalar(select(Build).where(Build.id == build_id))
        if build is not None:
            session.expunge(build)
        return build


def list_builds(
    *,
    limit: int = 50,
    db_url: str | None = None,
) -> list[Build]:
    """Return the most recent *limit* builds (newest first)."""
    with sync_session(db_url) as session:
        builds = session.scalars(select(Build).order_by(Build.created_at.desc()).limit(limit)).all()
        for b in builds:
            session.expunge(b)
        return list(builds)


# ---------------------------------------------------------------------------
# BuildJob
# ---------------------------------------------------------------------------


def create_build_job(
    build_id: str,
    step_kind: str,
    *,
    db_url: str | None = None,
) -> str:
    """Insert a ``BuildJob`` row with status ``"running"`` and return its ID."""
    with sync_session(db_url) as session:
        job = BuildJob(
            build_id=build_id,
            step_kind=step_kind,
            status="running",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def update_build_job(
    job_id: str,
    status: str,
    *,
    db_url: str | None = None,
) -> None:
    """Update ``BuildJob.status`` to *status*."""
    with sync_session(db_url) as session:
        job: BuildJob | None = session.scalar(select(BuildJob).where(BuildJob.id == job_id))
        if job is None:
            raise ValueError(f"build job not found: {job_id!r}")
        job.status = status
        session.commit()


def list_build_jobs(
    build_id: str,
    *,
    db_url: str | None = None,
) -> list[BuildJob]:
    """Return all ``BuildJob`` rows for *build_id*, ordered by creation."""
    with sync_session(db_url) as session:
        jobs = session.scalars(select(BuildJob).where(BuildJob.build_id == build_id)).all()
        for j in jobs:
            session.expunge(j)
        return list(jobs)


# ---------------------------------------------------------------------------
# BuildEvent
# ---------------------------------------------------------------------------


def log_build_event(
    build_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    job_id: str | None = None,
    db_url: str | None = None,
) -> None:
    """Append a ``BuildEvent`` row."""
    with sync_session(db_url) as session:
        event = BuildEvent(
            build_id=build_id,
            job_id=job_id,
            event_type=event_type,
            payload_json=payload or {},
        )
        session.add(event)
        session.commit()


def list_build_events(
    build_id: str,
    *,
    db_url: str | None = None,
) -> list[BuildEvent]:
    """Return all events for *build_id* in chronological order."""
    with sync_session(db_url) as session:
        events = session.scalars(
            select(BuildEvent).where(BuildEvent.build_id == build_id).order_by(BuildEvent.ts)
        ).all()
        for e in events:
            session.expunge(e)
        return list(events)
