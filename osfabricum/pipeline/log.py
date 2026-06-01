"""Build log persistence and retrieval (M19).

``write_build_log``
    Append a single log line to the ``build_logs`` table.

``write_build_logs``
    Bulk-append a list of strings from pipeline step output.

``get_build_logs``
    Return paginated log lines for a build.

``search_builds``
    Filter ``builds`` rows by status, distribution name, board, or date range.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import Build, BuildLog, Distribution
from osfabricum.db.session import sync_session

# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_build_log(
    build_id: str,
    message: str,
    *,
    job_id: str | None = None,
    stream: str = "stdout",
    line_no: int | None = None,
    db_url: str | None = None,
) -> None:
    """Append one log line to the ``build_logs`` table."""
    with sync_session(db_url) as session:
        session.add(
            BuildLog(
                build_id=build_id,
                job_id=job_id,
                stream=stream,
                line_no=line_no,
                message=message,
            )
        )
        session.commit()


def write_build_logs(
    build_id: str,
    lines: list[str],
    *,
    job_id: str | None = None,
    stream: str = "stdout",
    db_url: str | None = None,
) -> int:
    """Bulk-append *lines* to ``build_logs``.  Returns the number of rows inserted."""
    if not lines:
        return 0
    with sync_session(db_url) as session:
        for i, msg in enumerate(lines):
            session.add(
                BuildLog(
                    build_id=build_id,
                    job_id=job_id,
                    stream=stream,
                    line_no=i,
                    message=msg,
                )
            )
        session.commit()
    return len(lines)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_build_logs(
    build_id: str,
    *,
    job_id: str | None = None,
    stream: str | None = None,
    limit: int = 1000,
    offset: int = 0,
    db_url: str | None = None,
) -> list[BuildLog]:
    """Return paginated log lines for *build_id*.

    Parameters
    ----------
    build_id:
        UUID of the ``Build`` row.
    job_id:
        Filter to a specific ``BuildJob`` (optional).
    stream:
        ``"stdout"`` or ``"stderr"``; ``None`` returns all streams.
    limit:
        Maximum rows to return.
    offset:
        Number of rows to skip (for pagination).
    db_url:
        SQLAlchemy database URL.
    """
    with sync_session(db_url) as session:
        q = select(BuildLog).where(BuildLog.build_id == build_id)
        if job_id is not None:
            q = q.where(BuildLog.job_id == job_id)
        if stream is not None:
            q = q.where(BuildLog.stream == stream)
        q = q.order_by(BuildLog.ts, BuildLog.line_no).offset(offset).limit(limit)
        rows = session.scalars(q).all()
        for r in rows:
            session.expunge(r)
        return list(rows)


def count_build_logs(build_id: str, *, db_url: str | None = None) -> int:
    """Return the total number of log lines for *build_id*."""
    from sqlalchemy import func  # noqa: PLC0415

    with sync_session(db_url) as session:
        return session.scalar(
            select(func.count()).select_from(BuildLog).where(BuildLog.build_id == build_id)
        ) or 0


# ---------------------------------------------------------------------------
# Search / filter builds
# ---------------------------------------------------------------------------


def search_builds(
    *,
    distribution_name: str | None = None,
    status: str | None = None,
    board_id: str | None = None,
    since: datetime | None = None,
    limit: int = 50,
    db_url: str | None = None,
) -> list[Build]:
    """Return builds matching the given filters (newest first).

    Parameters
    ----------
    distribution_name:
        Filter by distribution name (exact match).
    status:
        Filter by ``Build.status`` (e.g. ``"success"``, ``"failed"``).
    board_id:
        Filter by ``Build.board_id``.
    since:
        Return only builds created after *since*.
    limit:
        Maximum rows.
    """
    with sync_session(db_url) as session:
        q = select(Build)

        if distribution_name is not None:
            dist: Distribution | None = session.scalar(
                select(Distribution).where(Distribution.name == distribution_name)
            )
            if dist is None:
                return []
            q = q.where(Build.distribution_id == dist.id)

        if status is not None:
            q = q.where(Build.status == status)

        if board_id is not None:
            q = q.where(Build.board_id == board_id)

        if since is not None:
            q = q.where(Build.created_at >= since)

        q = q.order_by(Build.created_at.desc()).limit(limit)
        builds = session.scalars(q).all()
        for b in builds:
            session.expunge(b)
        return list(builds)


def build_summary(
    build_id: str,
    *,
    db_url: str | None = None,
) -> dict[str, Any] | None:
    """Return a JSON-serializable summary dict for *build_id*.

    Returns ``None`` if the build is not found.
    """
    from osfabricum.pipeline.record import (  # noqa: PLC0415
        get_build,
        list_build_events,
        list_build_jobs,
    )

    build = get_build(build_id, db_url=db_url)
    if build is None:
        return None

    jobs = list_build_jobs(build_id, db_url=db_url)
    events = list_build_events(build_id, db_url=db_url)
    log_count = count_build_logs(build_id, db_url=db_url)

    return {
        "id": build.id,
        "distribution_id": build.distribution_id,
        "profile_id": build.profile_id,
        "board_id": build.board_id,
        "resolution_hash": build.resolution_hash,
        "status": build.status,
        "created_at": build.created_at.isoformat() if build.created_at else None,
        "updated_at": build.updated_at.isoformat() if build.updated_at else None,
        "jobs": [
            {"id": j.id, "step_kind": j.step_kind, "status": j.status}
            for j in jobs
        ],
        "event_count": len(events),
        "log_line_count": log_count,
    }
