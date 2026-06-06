"""Filesystem / Image Recipe Designer (M34).

Models output images as data — formats, filesystems, partition layouts and
sizing policies are DB records, not the single hardcoded raw format / fixed
sizes the pipeline used to assume (closes G-06). :func:`estimate_recipe` turns a
recipe into a deterministic partition-size plan the pipeline can consume.

The multi-format *compose execution* (qcow2/iso/squashfs/erofs/…) is a follow-on
that extends ``image.compose``; this module owns the data model, the
estimator/resolver and the recipe catalog.
"""

from __future__ import annotations

from osfabricum.imagedesign.service import (
    add_mount,
    add_output,
    add_overlay,
    add_partition,
    create_filesystem_profile,
    create_partition_layout,
    create_recipe,
    create_size_policy,
    estimate_recipe,
    list_filesystem_profiles,
    list_partition_layouts,
    list_recipes,
    list_size_policies,
    resolve_recipe,
    set_recipe_targets,
)

__all__ = [
    "add_mount",
    "add_output",
    "add_overlay",
    "add_partition",
    "create_filesystem_profile",
    "create_partition_layout",
    "create_recipe",
    "create_size_policy",
    "estimate_recipe",
    "list_filesystem_profiles",
    "list_partition_layouts",
    "list_recipes",
    "list_size_policies",
    "resolve_recipe",
    "set_recipe_targets",
]
