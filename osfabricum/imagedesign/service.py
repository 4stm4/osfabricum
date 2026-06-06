"""Filesystem / Image Recipe Designer service (M34).

Image recipes are *data*, not hardcoded formats and sizes (closes G-06). A
recipe ties a reusable partition layout, filesystem profiles and a sizing policy
together and declares one or more output formats. The heart is
:func:`estimate_recipe`: it walks the partition layout, applies the size policy
(alignment, reserve, free space, grow-to-fit) and produces a deterministic size
plan — so the pipeline reads partition sizes from the recipe instead of the old
``boot_size_mb=4`` / ``rootfs_size_mb=16`` constants.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osfabricum.db.models import (
    FilesystemProfile,
    ImageOutput,
    ImageRecipe,
    MountPolicy,
    OverlayPolicy,
    PartitionEntry,
    PartitionLayout,
    SizePolicy,
)
from osfabricum.db.session import sync_session

KNOWN_FORMATS = (
    "raw",
    "qcow2",
    "vmdk",
    "iso",
    "tarball",
    "update-bundle",
    "sdcard",
    "usb",
    "netboot",
    "container",
    "vmimage",
)
KNOWN_FILESYSTEMS = ("ext4", "squashfs", "erofs", "btrfs", "xfs", "vfat", "overlayfs", "tmpfs")
_ROOT_ROLE = "rootfs"
_AB_ROLES = ("ab_a", "ab_b")

# Defaults applied when a recipe has no explicit size policy.
_DEFAULT_POLICY = {
    "free_space_pct": 0,
    "min_free_mb": 0,
    "align_mb": 4,
    "reserve_mb": 1,
    "grow_to_fit": True,
}


def _align_up(value: int, align: int) -> int:
    if align <= 1:
        return max(value, 0)
    return ((max(value, 0) + align - 1) // align) * align


# ---------------------------------------------------------------------------
# Filesystem profiles
# ---------------------------------------------------------------------------


def create_filesystem_profile(
    name: str,
    fs_type: str,
    *,
    label: str | None = None,
    mount_point: str | None = None,
    read_only: bool = False,
    compression: str | None = None,
    options: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    if fs_type not in KNOWN_FILESYSTEMS:
        raise ValueError(
            f"unknown filesystem type: {fs_type!r} (known: {', '.join(KNOWN_FILESYSTEMS)})"
        )
    with sync_session(db_url) as s:
        if s.scalar(select(FilesystemProfile).where(FilesystemProfile.name == name)) is not None:
            raise ValueError(f"filesystem profile already exists: {name!r}")
        fs = FilesystemProfile(
            name=name,
            fs_type=fs_type,
            label=label,
            mount_point=mount_point,
            read_only=read_only,
            compression=compression,
            options_json=options,
        )
        s.add(fs)
        s.commit()
        return {"id": fs.id, "name": name, "fs_type": fs_type}


def list_filesystem_profiles(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "id": f.id,
                "name": f.name,
                "fs_type": f.fs_type,
                "label": f.label,
                "mount_point": f.mount_point,
                "read_only": f.read_only,
                "compression": f.compression,
            }
            for f in s.scalars(select(FilesystemProfile).order_by(FilesystemProfile.name)).all()
        ]


# ---------------------------------------------------------------------------
# Size policies
# ---------------------------------------------------------------------------


def create_size_policy(
    name: str,
    *,
    free_space_pct: int = 0,
    min_free_mb: int = 0,
    align_mb: int = 4,
    reserve_mb: int = 1,
    grow_to_fit: bool = True,
    db_url: str | None = None,
) -> dict[str, Any]:
    if align_mb < 1:
        raise ValueError("align_mb must be >= 1")
    if free_space_pct < 0 or min_free_mb < 0 or reserve_mb < 0:
        raise ValueError("size policy values must be non-negative")
    with sync_session(db_url) as s:
        if s.scalar(select(SizePolicy).where(SizePolicy.name == name)) is not None:
            raise ValueError(f"size policy already exists: {name!r}")
        sp = SizePolicy(
            name=name,
            free_space_pct=free_space_pct,
            min_free_mb=min_free_mb,
            align_mb=align_mb,
            reserve_mb=reserve_mb,
            grow_to_fit=grow_to_fit,
        )
        s.add(sp)
        s.commit()
        return {"id": sp.id, "name": name}


def list_size_policies(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        return [
            {
                "id": p.id,
                "name": p.name,
                "free_space_pct": p.free_space_pct,
                "min_free_mb": p.min_free_mb,
                "align_mb": p.align_mb,
                "reserve_mb": p.reserve_mb,
                "grow_to_fit": p.grow_to_fit,
            }
            for p in s.scalars(select(SizePolicy).order_by(SizePolicy.name)).all()
        ]


# ---------------------------------------------------------------------------
# Partition layouts
# ---------------------------------------------------------------------------


def create_partition_layout(
    name: str, *, board_id: str | None = None, db_url: str | None = None
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        if s.scalar(select(PartitionLayout).where(PartitionLayout.name == name)) is not None:
            raise ValueError(f"partition layout already exists: {name!r}")
        layout = PartitionLayout(name=name, board_id=board_id)
        s.add(layout)
        s.commit()
        return {"id": layout.id, "name": name}


def _layout_or_raise(s: Session, layout_id: str) -> PartitionLayout:
    layout = s.get(PartitionLayout, layout_id)
    if layout is None:
        raise ValueError(f"partition layout not found: {layout_id!r}")
    return layout


def add_partition(
    layout_id: str,
    name: str,
    role: str,
    *,
    filesystem_id: str | None = None,
    size_mb: int | None = None,
    grow: bool = False,
    position: int | None = None,
    flags: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    if size_mb is not None and size_mb <= 0:
        raise ValueError("size_mb must be positive (omit it for a grow partition)")
    with sync_session(db_url) as s:
        _layout_or_raise(s, layout_id)
        if position is None:
            existing = s.scalars(
                select(PartitionEntry.position).where(PartitionEntry.layout_id == layout_id)
            ).all()
            position = (max(existing) + 1) if existing else 0
        entry = PartitionEntry(
            layout_id=layout_id,
            name=name,
            role=role,
            filesystem_id=filesystem_id,
            size_mb=size_mb,
            grow=grow,
            position=position,
            flags_json=flags,
        )
        s.add(entry)
        s.commit()
        return {"id": entry.id, "layout_id": layout_id, "name": name, "role": role}


def list_partition_layouts(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        out: list[dict[str, Any]] = []
        for layout in s.scalars(select(PartitionLayout).order_by(PartitionLayout.name)).all():
            count = len(
                s.scalars(
                    select(PartitionEntry.id).where(PartitionEntry.layout_id == layout.id)
                ).all()
            )
            out.append(
                {
                    "id": layout.id,
                    "name": layout.name,
                    "board_id": layout.board_id,
                    "partition_count": count,
                }
            )
        return out


# ---------------------------------------------------------------------------
# Image recipes
# ---------------------------------------------------------------------------


def create_recipe(
    name: str,
    *,
    distribution_id: str | None = None,
    output_format: str = "raw",
    description: str | None = None,
    partition_layout_id: str | None = None,
    size_policy_id: str | None = None,
    root_filesystem_id: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    if output_format not in KNOWN_FORMATS:
        raise ValueError(f"unknown output format: {output_format!r}")
    with sync_session(db_url) as s:
        dup = s.scalar(
            select(ImageRecipe).where(
                ImageRecipe.name == name, ImageRecipe.distribution_id == distribution_id
            )
        )
        if dup is not None:
            raise ValueError(f"image recipe already exists: {name!r}")
        recipe = ImageRecipe(
            name=name,
            distribution_id=distribution_id,
            output_format=output_format,
            description=description,
            partition_layout_id=partition_layout_id,
            size_policy_id=size_policy_id,
            root_filesystem_id=root_filesystem_id,
        )
        s.add(recipe)
        s.commit()
        return {"id": recipe.id, "name": name}


def _recipe_or_raise(s: Session, recipe_id: str) -> ImageRecipe:
    recipe = s.get(ImageRecipe, recipe_id)
    if recipe is None:
        raise ValueError(f"image recipe not found: {recipe_id!r}")
    return recipe


def set_recipe_targets(
    recipe_id: str,
    *,
    partition_layout_id: str | None = None,
    size_policy_id: str | None = None,
    root_filesystem_id: str | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Attach a partition layout / size policy / root filesystem to a recipe."""
    with sync_session(db_url) as s:
        recipe = _recipe_or_raise(s, recipe_id)
        if partition_layout_id is not None:
            recipe.partition_layout_id = partition_layout_id
        if size_policy_id is not None:
            recipe.size_policy_id = size_policy_id
        if root_filesystem_id is not None:
            recipe.root_filesystem_id = root_filesystem_id
        s.commit()
        return {
            "id": recipe.id,
            "partition_layout_id": recipe.partition_layout_id,
            "size_policy_id": recipe.size_policy_id,
            "root_filesystem_id": recipe.root_filesystem_id,
        }


def add_output(
    recipe_id: str,
    output_format: str,
    *,
    compression: str | None = None,
    filename_template: str | None = None,
    position: int | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    if output_format not in KNOWN_FORMATS:
        raise ValueError(f"unknown output format: {output_format!r}")
    with sync_session(db_url) as s:
        _recipe_or_raise(s, recipe_id)
        if position is None:
            existing = s.scalars(
                select(ImageOutput.position).where(ImageOutput.recipe_id == recipe_id)
            ).all()
            position = (max(existing) + 1) if existing else 0
        out = ImageOutput(
            recipe_id=recipe_id,
            output_format=output_format,
            compression=compression,
            filename_template=filename_template,
            position=position,
        )
        s.add(out)
        s.commit()
        return {"id": out.id, "recipe_id": recipe_id, "output_format": output_format}


def add_mount(
    recipe_id: str,
    source: str,
    target: str,
    fstype: str,
    *,
    options: str | None = None,
    position: int | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        _recipe_or_raise(s, recipe_id)
        if position is None:
            existing = s.scalars(
                select(MountPolicy.position).where(MountPolicy.recipe_id == recipe_id)
            ).all()
            position = (max(existing) + 1) if existing else 0
        mount = MountPolicy(
            recipe_id=recipe_id,
            source=source,
            target=target,
            fstype=fstype,
            options=options,
            position=position,
        )
        s.add(mount)
        s.commit()
        return {"id": mount.id, "recipe_id": recipe_id, "target": target}


def add_overlay(
    recipe_id: str,
    target: str,
    lower_dir: str,
    upper_dir: str,
    work_dir: str,
    *,
    persistent: bool = False,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        _recipe_or_raise(s, recipe_id)
        overlay = OverlayPolicy(
            recipe_id=recipe_id,
            target=target,
            lower_dir=lower_dir,
            upper_dir=upper_dir,
            work_dir=work_dir,
            persistent=persistent,
        )
        s.add(overlay)
        s.commit()
        return {"id": overlay.id, "recipe_id": recipe_id, "target": target}


def list_recipes(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        out: list[dict[str, Any]] = []
        for r in s.scalars(select(ImageRecipe).order_by(ImageRecipe.name)).all():
            formats = [r.output_format] + [
                o.output_format
                for o in s.scalars(select(ImageOutput).where(ImageOutput.recipe_id == r.id)).all()
            ]
            out.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "distribution_id": r.distribution_id,
                    "output_format": r.output_format,
                    "formats": sorted(set(formats)),
                    "has_layout": r.partition_layout_id is not None,
                }
            )
        return out


def _load_partitions(s: Session, layout_id: str) -> list[PartitionEntry]:
    return list(
        s.scalars(
            select(PartitionEntry)
            .where(PartitionEntry.layout_id == layout_id)
            .order_by(PartitionEntry.position)
        ).all()
    )


def resolve_recipe(recipe_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    """Expand a recipe into its full definition (layout, policy, outputs, mounts)."""
    with sync_session(db_url) as s:
        recipe = _recipe_or_raise(s, recipe_id)
        fs_names = {f.id: f for f in s.scalars(select(FilesystemProfile)).all()}

        partitions: list[dict[str, Any]] = []
        if recipe.partition_layout_id:
            for p in _load_partitions(s, recipe.partition_layout_id):
                fs = fs_names.get(p.filesystem_id) if p.filesystem_id else None
                partitions.append(
                    {
                        "name": p.name,
                        "role": p.role,
                        "size_mb": p.size_mb,
                        "grow": p.grow,
                        "filesystem": fs.name if fs else None,
                        "fs_type": fs.fs_type if fs else None,
                    }
                )

        policy = s.get(SizePolicy, recipe.size_policy_id) if recipe.size_policy_id else None
        outputs = [recipe.output_format] + [
            o.output_format
            for o in s.scalars(
                select(ImageOutput)
                .where(ImageOutput.recipe_id == recipe_id)
                .order_by(ImageOutput.position)
            ).all()
        ]
        mounts = [
            {"source": m.source, "target": m.target, "fstype": m.fstype, "options": m.options}
            for m in s.scalars(
                select(MountPolicy)
                .where(MountPolicy.recipe_id == recipe_id)
                .order_by(MountPolicy.position)
            ).all()
        ]
        overlays = [
            {
                "target": o.target,
                "lower_dir": o.lower_dir,
                "upper_dir": o.upper_dir,
                "work_dir": o.work_dir,
                "persistent": o.persistent,
            }
            for o in s.scalars(
                select(OverlayPolicy).where(OverlayPolicy.recipe_id == recipe_id)
            ).all()
        ]
        return {
            "id": recipe.id,
            "name": recipe.name,
            "outputs": sorted(set(outputs)),
            "partitions": partitions,
            "mounts": mounts,
            "overlays": overlays,
            "size_policy": (
                {
                    "name": policy.name,
                    "free_space_pct": policy.free_space_pct,
                    "min_free_mb": policy.min_free_mb,
                    "align_mb": policy.align_mb,
                    "reserve_mb": policy.reserve_mb,
                    "grow_to_fit": policy.grow_to_fit,
                }
                if policy
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Estimator (the heart, G-06)
# ---------------------------------------------------------------------------


def estimate_recipe(
    recipe_id: str, *, total_disk_mb: int | None = None, db_url: str | None = None
) -> dict[str, Any]:
    """Compute a deterministic partition-size plan for a recipe.

    Walks the recipe's partition layout, validates the role set (exactly one
    rootfs, or a matched A/B pair), then applies the size policy: every fixed
    partition keeps its size; grow partitions absorb free space (a share of
    ``total_disk_mb`` if given, else ``size + free_space_pct% + min_free``);
    each size is aligned up; leading/trailing reserve is added. Returns the plan
    plus a content hash so the result can feed ``resolution_hash``.
    """
    with sync_session(db_url) as s:
        recipe = _recipe_or_raise(s, recipe_id)
        if not recipe.partition_layout_id:
            raise ValueError("recipe has no partition layout to estimate")
        entries = _load_partitions(s, recipe.partition_layout_id)
        fs_by_id = {f.id: f for f in s.scalars(select(FilesystemProfile)).all()}
        policy_row = s.get(SizePolicy, recipe.size_policy_id) if recipe.size_policy_id else None
        outputs = sorted(
            {recipe.output_format}
            | {
                o.output_format
                for o in s.scalars(
                    select(ImageOutput).where(ImageOutput.recipe_id == recipe_id)
                ).all()
            }
        )

    policy = (
        {
            "free_space_pct": policy_row.free_space_pct,
            "min_free_mb": policy_row.min_free_mb,
            "align_mb": policy_row.align_mb,
            "reserve_mb": policy_row.reserve_mb,
            "grow_to_fit": policy_row.grow_to_fit,
        }
        if policy_row
        else dict(_DEFAULT_POLICY)
    )

    errors: list[str] = []
    warnings: list[str] = []

    if not entries:
        errors.append("partition layout has no partitions")

    roles = [e.role for e in entries]
    root_count = roles.count(_ROOT_ROLE)
    has_ab = all(r in roles for r in _AB_ROLES)
    if any(r in roles for r in _AB_ROLES) and not has_ab:
        errors.append("A/B layout needs both ab_a and ab_b partitions")
    if root_count == 0 and not has_ab:
        errors.append("layout has no root partition (role 'rootfs' or an ab_a/ab_b pair)")
    if root_count > 1:
        errors.append(f"layout has {root_count} root partitions (expected exactly one)")
    if has_ab:
        ab_sizes = {e.role: e.size_mb for e in entries if e.role in _AB_ROLES}
        if ab_sizes.get("ab_a") != ab_sizes.get("ab_b"):
            errors.append("A/B slots must be equal size")

    grow_entries = [e for e in entries if e.grow]
    if len(grow_entries) > 1:
        warnings.append(f"{len(grow_entries)} grow partitions — free space is split evenly")

    align = policy["align_mb"]
    fixed_total = sum(_align_up(e.size_mb or 0, align) for e in entries if e not in grow_entries)

    # Compute grow sizes.
    grow_sizes: dict[str, int] = {}
    if grow_entries:
        if total_disk_mb is not None:
            usable = total_disk_mb - fixed_total - 2 * policy["reserve_mb"]
            if usable <= 0:
                errors.append(
                    f"fixed partitions ({fixed_total} MiB) exceed total disk ({total_disk_mb} MiB)"
                )
                usable = 0
            share = usable // len(grow_entries)
            for e in grow_entries:
                grow_sizes[e.id] = _align_up(max(share, policy["min_free_mb"]), align)
        else:
            for e in grow_entries:
                base = e.size_mb or 0
                inflated = base + (base * policy["free_space_pct"]) // 100 + policy["min_free_mb"]
                grow_sizes[e.id] = _align_up(max(inflated, 1), align)

    partitions: list[dict[str, Any]] = []
    for e in entries:
        size = grow_sizes[e.id] if e in grow_entries else _align_up(e.size_mb or 0, align)
        fs = fs_by_id.get(e.filesystem_id) if e.filesystem_id else None
        if not e.grow and e.size_mb is None:
            errors.append(f"partition {e.name!r} has no size and is not a grow partition")
        partitions.append(
            {
                "name": e.name,
                "role": e.role,
                "size_mb": size,
                "grow": e in grow_entries,
                "fs_type": fs.fs_type if fs else None,
            }
        )

    total_image_mb = 2 * policy["reserve_mb"] + sum(p["size_mb"] for p in partitions)

    plan = {"partitions": partitions, "outputs": outputs, "total_image_mb": total_image_mb}
    plan_hash = (
        "sha256:" + hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()
    )

    return {
        "recipe": recipe_id,
        "outputs": outputs,
        "partitions": partitions,
        "total_image_mb": total_image_mb,
        "size_policy": policy,
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
        "plan_hash": plan_hash,
    }
