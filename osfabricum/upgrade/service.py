"""Business logic for M61 — Attended Upgrade / Rebuild Service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import UpgradeRequest, UpgradeResult, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "success", "failed", "cancelled"}
)


def create_upgrade_request(
    session: "Session",
    distribution_id: str | None = None,
    profile_id: str | None = None,
    current_generation_id: str | None = None,
    target_channel: str = "stable",
    target_version: str | None = None,
) -> UpgradeRequest:
    req = UpgradeRequest(
        id=_uuid(),
        distribution_id=distribution_id,
        profile_id=profile_id,
        current_generation_id=current_generation_id,
        target_channel=target_channel,
        target_version=target_version,
        status="pending",
        requested_at=_now(),
        completed_at=None,
        result_json=None,
    )
    session.add(req)
    session.flush()
    return req


def list_upgrade_requests(
    session: "Session",
    distribution_id: str | None = None,
    status: str | None = None,
) -> list[UpgradeRequest]:
    q = select(UpgradeRequest).order_by(UpgradeRequest.requested_at.desc())
    if distribution_id is not None:
        q = q.where(UpgradeRequest.distribution_id == distribution_id)
    if status is not None:
        q = q.where(UpgradeRequest.status == status)
    return list(session.scalars(q).all())


def get_upgrade_request(session: "Session", upgrade_id: str) -> UpgradeRequest:
    req = session.get(UpgradeRequest, upgrade_id)
    if req is None:
        raise KeyError(f"UpgradeRequest {upgrade_id!r} not found")
    return req


def update_upgrade_status(
    session: "Session",
    upgrade_id: str,
    status: str,
) -> UpgradeRequest:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}. Valid: {sorted(VALID_STATUSES)}")
    req = get_upgrade_request(session, upgrade_id)
    req.status = status
    if status in ("success", "failed", "cancelled"):
        req.completed_at = _now()
    session.flush()
    return req


def record_upgrade_result(
    session: "Session",
    upgrade_id: str,
    status: str,
    new_generation_id: str | None = None,
    artifact_id: str | None = None,
    diff_report_id: str | None = None,
    rollback_plan: str | None = None,
    error_message: str | None = None,
) -> UpgradeResult:
    result = UpgradeResult(
        id=_uuid(),
        upgrade_id=upgrade_id,
        status=status,
        new_generation_id=new_generation_id,
        artifact_id=artifact_id,
        diff_report_id=diff_report_id,
        rollback_plan=rollback_plan,
        error_message=error_message,
        created_at=_now(),
    )
    session.add(result)
    req = session.get(UpgradeRequest, upgrade_id)
    if req is not None:
        req.status = status
        if status in ("success", "failed"):
            req.completed_at = _now()
    session.flush()
    return result


def list_upgrade_results(
    session: "Session", upgrade_id: str
) -> list[UpgradeResult]:
    return list(
        session.scalars(
            select(UpgradeResult)
            .where(UpgradeResult.upgrade_id == upgrade_id)
            .order_by(UpgradeResult.created_at.desc())
        ).all()
    )
