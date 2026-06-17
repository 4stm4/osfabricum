"""M67 — Distributed Build Farm / Worker Pools public API."""

from osfabricum.workerpool.service import (
    VALID_POOL_KINDS,
    VALID_RESOURCE_KINDS,
    add_job_affinity,
    add_pool_member,
    create_worker_pool,
    get_worker_pool,
    list_job_affinities,
    list_pool_members,
    list_pool_quotas,
    list_worker_pools,
    set_pool_quota,
    update_worker_pool,
)

__all__ = [
    "VALID_POOL_KINDS",
    "VALID_RESOURCE_KINDS",
    "add_job_affinity",
    "add_pool_member",
    "create_worker_pool",
    "get_worker_pool",
    "list_job_affinities",
    "list_pool_members",
    "list_pool_quotas",
    "list_worker_pools",
    "set_pool_quota",
    "update_worker_pool",
]
