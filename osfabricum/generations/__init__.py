"""M60 — System Generations / Rollback Designer public API."""

from osfabricum.generations.service import (
    VALID_ARTIFACT_ROLES,
    VALID_ROLLBACK_KINDS,
    VALID_STATUSES,
    add_generation_artifact,
    add_rollback_target,
    create_generation,
    get_generation,
    list_generations,
    list_rollback_kinds,
    render_generation_manifest,
    render_rollback_plan,
    update_generation,
)

__all__ = [
    "VALID_ARTIFACT_ROLES",
    "VALID_ROLLBACK_KINDS",
    "VALID_STATUSES",
    "add_generation_artifact",
    "add_rollback_target",
    "create_generation",
    "get_generation",
    "list_generations",
    "list_rollback_kinds",
    "render_generation_manifest",
    "render_rollback_plan",
    "update_generation",
]
