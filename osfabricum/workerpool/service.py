"""Business logic for M67 — Distributed Build Farm / Worker Pools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import (
    JobAffinity,
    PoolQuota,
    WorkerPool,
    WorkerPoolMember,
    _now,
    _uuid,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_POOL_KINDS: frozenset[str] = frozenset(
    {"local", "remote", "trusted", "signing-only", "hardware-lab", "qemu-test"}
)
VALID_RESOURCE_KINDS: frozenset[str] = frozenset({"cpu", "memory", "disk", "network"})


def create_worker_pool(
    session: "Session",
    name: str,
    pool_kind: str = "local",
    label: str = "",
    description: str = "",
    max_parallelism: int = 1,
) -> WorkerPool:
    if pool_kind not in VALID_POOL_KINDS:
        raise ValueError(
            f"Invalid pool_kind {pool_kind!r}. Valid: {sorted(VALID_POOL_KINDS)}"
        )
    pool = WorkerPool(
        id=_uuid(), name=name, label=label, description=description,
        pool_kind=pool_kind, max_parallelism=max_parallelism,
        created_at=_now(), updated_at=_now(),
    )
    session.add(pool)
    session.flush()
    return pool


def list_worker_pools(
    session: "Session", pool_kind: str | None = None
) -> list[WorkerPool]:
    q = select(WorkerPool).order_by(WorkerPool.name)
    if pool_kind is not None:
        q = q.where(WorkerPool.pool_kind == pool_kind)
    return list(session.scalars(q).all())


def get_worker_pool(session: "Session", pool_id: str) -> WorkerPool:
    pool = session.get(WorkerPool, pool_id)
    if pool is None:
        raise KeyError(f"WorkerPool {pool_id!r} not found")
    return pool


def update_worker_pool(
    session: "Session",
    pool_id: str,
    label: str | None = None,
    description: str | None = None,
    max_parallelism: int | None = None,
    pool_kind: str | None = None,
) -> WorkerPool:
    pool = get_worker_pool(session, pool_id)
    if label is not None:
        pool.label = label
    if description is not None:
        pool.description = description
    if max_parallelism is not None:
        pool.max_parallelism = max_parallelism
    if pool_kind is not None:
        if pool_kind not in VALID_POOL_KINDS:
            raise ValueError(
                f"Invalid pool_kind {pool_kind!r}. Valid: {sorted(VALID_POOL_KINDS)}"
            )
        pool.pool_kind = pool_kind
    pool.updated_at = _now()
    session.flush()
    return pool


def add_pool_member(
    session: "Session", pool_id: str, worker_id: str | None = None
) -> WorkerPoolMember:
    member = WorkerPoolMember(
        id=_uuid(), worker_pool_id=pool_id, worker_id=worker_id, joined_at=_now()
    )
    session.add(member)
    session.flush()
    return member


def list_pool_members(
    session: "Session", pool_id: str
) -> list[WorkerPoolMember]:
    return list(
        session.scalars(
            select(WorkerPoolMember)
            .where(WorkerPoolMember.worker_pool_id == pool_id)
            .order_by(WorkerPoolMember.joined_at)
        ).all()
    )


def add_job_affinity(
    session: "Session", pool_id: str, job_kind: str, weight: int = 1
) -> JobAffinity:
    aff = JobAffinity(
        id=_uuid(), pool_id=pool_id, job_kind=job_kind, affinity_weight=weight
    )
    session.add(aff)
    session.flush()
    return aff


def set_pool_quota(
    session: "Session",
    pool_id: str,
    resource_kind: str,
    limit_value: int,
    period_seconds: int = 3600,
) -> PoolQuota:
    if resource_kind not in VALID_RESOURCE_KINDS:
        raise ValueError(
            f"Invalid resource_kind {resource_kind!r}. "
            f"Valid: {sorted(VALID_RESOURCE_KINDS)}"
        )
    existing = session.scalars(
        select(PoolQuota).where(
            PoolQuota.pool_id == pool_id,
            PoolQuota.resource_kind == resource_kind,
        )
    ).first()
    if existing is not None:
        existing.limit_value = limit_value
        existing.period_seconds = period_seconds
    else:
        existing = PoolQuota(
            id=_uuid(), pool_id=pool_id, resource_kind=resource_kind,
            limit_value=limit_value, period_seconds=period_seconds,
        )
        session.add(existing)
    session.flush()
    return existing


def list_job_affinities(
    session: "Session", pool_id: str
) -> list[JobAffinity]:
    return list(
        session.scalars(
            select(JobAffinity).where(JobAffinity.pool_id == pool_id)
            .order_by(JobAffinity.job_kind)
        ).all()
    )


def list_pool_quotas(session: "Session", pool_id: str) -> list[PoolQuota]:
    return list(
        session.scalars(
            select(PoolQuota).where(PoolQuota.pool_id == pool_id)
            .order_by(PoolQuota.resource_kind)
        ).all()
    )
