"""Package Workspace / Package Manager (M35).

Organizes packages by kind and layer, groups/sets them for reuse across
distributions, and reasons about the package cache — replacing the flat
``Package.package_type`` string and the all-packages-per-arch selection (closes
G-04, G-28). The cache key folds in source/recipe/feature/toolchain/ABI hashes
and the kernel binding for kernel-bound kinds, so a kernel module is never
reused across an incompatible kernel; every hit/miss is explained.

Feeds (M37) and variant features (M36) are modelled here but their publishing /
feature-resolution behaviour lands in those milestones.
"""

from __future__ import annotations

from osfabricum.packageworkspace.features import (
    FEATURE_TYPES,
    add_variant_artifact,
    define_feature,
    diff_variants,
    list_build_variants,
    list_features,
    record_build_variant,
    resolve_variant,
)
from osfabricum.packageworkspace.service import (
    KERNEL_BOUND_KINDS,
    add_feed_index,
    add_to_group,
    add_to_set,
    cache_stats,
    classify_package,
    compute_cache_key,
    create_feed,
    create_group,
    create_lock,
    create_set,
    create_variant,
    explain_cache,
    list_feeds,
    list_groups,
    list_kinds,
    list_layers,
    list_locks,
    list_sets,
    list_variants,
    lookup_cache,
    promote,
    record_cache_entry,
    resolve_set,
)

__all__ = [
    "FEATURE_TYPES",
    "KERNEL_BOUND_KINDS",
    "add_feed_index",
    "add_to_group",
    "add_to_set",
    "add_variant_artifact",
    "cache_stats",
    "classify_package",
    "compute_cache_key",
    "create_feed",
    "create_group",
    "create_lock",
    "create_set",
    "create_variant",
    "define_feature",
    "diff_variants",
    "explain_cache",
    "list_build_variants",
    "list_feeds",
    "list_features",
    "list_groups",
    "list_kinds",
    "list_layers",
    "list_locks",
    "list_sets",
    "list_variants",
    "lookup_cache",
    "promote",
    "record_build_variant",
    "record_cache_entry",
    "resolve_set",
    "resolve_variant",
]
