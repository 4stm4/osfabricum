"""Build Plan Resolver (M12).

``resolve_plan`` is the entry point.  Given a ``(distribution, profile, board)``
triple it queries the database and produces a :class:`~.plan.BuildPlan` with:

* Resolved toolchain, kernel, packages, firmware, overlays, scripts,
  partition layout
* A deterministic ``resolution_hash`` (SHA-256 of the sorted input IDs)
* ``missing_artifacts`` — human-readable descriptions of what is not yet built
* ``required_jobs`` — job-kind strings that need to run to complete the build

Profile inheritance
-------------------
Profiles can inherit from other profiles via ``Profile.inherits_id``.
The resolver walks the inheritance chain (child → parent → grandparent …)
and merges ``inputs_json`` top-down (child keys override parent keys).
Cycles are detected by tracking visited IDs.

Resolution hash
---------------
The hash input is a stable JSON object:

.. code-block:: json

    {
      "distribution_id": "...",
      "profile_id": "...",
      "board_id": "...",
      "arch_id": "...",
      "toolchain_id": "...",
      "kernel_id": "...",
      "package_version_ids": ["..."],
      "firmware_blob_ids": ["..."],
      "overlay_ids": ["..."],
      "script_ids": ["..."]
    }

All list fields are sorted.  The object is serialized with
``separators=(',', ':')`` for determinism, then SHA-256-hashed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from osfabricum.db.models import (
    Architecture,
    Board,
    Distribution,
    FirmwareBlob,
    Kernel,
    KernelConfig,
    Overlay,
    Package,
    PackageGroupMember,
    PackageSetMember,
    PackageVersion,
    PartitionLayout,
    Profile,
    Script,
    Toolchain,
    ToolchainArtifact,
)
from osfabricum.db.session import sync_session
from osfabricum.resolver.plan import (
    BuildPlan,
    FirmwareRef,
    KernelRef,
    OverlayRef,
    PackageRef,
    PartitionLayoutRef,
    ScriptRef,
    ToolchainRef,
)

_MAX_INHERIT_DEPTH = 32  # guard against inheritance cycles


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_profile_chain(profile: Profile, session: Any) -> list[Profile]:
    """Return the profile chain from *profile* up to the root ancestor.

    The first element is *profile*; subsequent elements are its ancestors.
    """
    chain: list[Profile] = [profile]
    visited: set[str] = {profile.id}
    current = profile
    for _ in range(_MAX_INHERIT_DEPTH):
        if current.inherits_id is None:
            break
        if current.inherits_id in visited:
            raise ValueError(f"profile inheritance cycle detected at id={current.inherits_id!r}")
        parent: Profile | None = session.scalar(
            select(Profile).where(Profile.id == current.inherits_id)
        )
        if parent is None:
            break
        chain.append(parent)
        visited.add(parent.id)
        current = parent
    return chain


def _merge_inputs(chain: list[Profile]) -> dict[str, Any]:
    """Merge ``inputs_json`` from the profile chain (child overrides parent)."""
    merged: dict[str, Any] = {}
    for profile in reversed(chain):  # parent first, child last
        merged.update(profile.inputs_json or {})
    return merged


def _compute_resolution_hash(payload: dict[str, Any]) -> str:
    """Return ``sha256:<hex>`` of the stable-serialized *payload*."""
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _packages_from_set(session: Any, set_id: str, arch_id: str) -> list[PackageVersion]:
    """Expand a package set (direct packages + group members) → arch versions."""
    package_ids: set[str] = set()
    for member in session.scalars(
        select(PackageSetMember).where(PackageSetMember.set_id == set_id)
    ).all():
        if member.member_kind == "package" and member.package_id:
            package_ids.add(member.package_id)
        elif member.member_kind == "group" and member.group_id:
            for gm in session.scalars(
                select(PackageGroupMember).where(PackageGroupMember.group_id == member.group_id)
            ).all():
                package_ids.add(gm.package_id)
    if not package_ids:
        return []
    return list(
        session.scalars(
            select(PackageVersion).where(
                PackageVersion.package_id.in_(package_ids),
                PackageVersion.arch_id == arch_id,
            )
        ).all()
    )


def _packages_by_name(session: Any, names: list[str], arch_id: str) -> list[PackageVersion]:
    """Select arch package versions for the named packages (from profile inputs)."""
    pkg_ids = [p.id for p in session.scalars(select(Package).where(Package.name.in_(names))).all()]
    if not pkg_ids:
        return []
    return list(
        session.scalars(
            select(PackageVersion).where(
                PackageVersion.package_id.in_(pkg_ids),
                PackageVersion.arch_id == arch_id,
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_plan(
    distribution_name: str,
    profile_name: str,
    board_name: str,
    *,
    db_url: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> BuildPlan:
    """Resolve a full build plan for the given triple.

    Parameters
    ----------
    distribution_name:
        Name of the :class:`~osfabricum.db.models.Distribution` row.
    profile_name:
        Name of the :class:`~osfabricum.db.models.Profile` row.
    board_name:
        Name of the :class:`~osfabricum.db.models.Board` row.
    db_url:
        SQLAlchemy database URL.  ``None`` uses the default from settings.

    Returns
    -------
    BuildPlan
        The fully resolved build plan.

    Raises
    ------
    ValueError
        If any of the three required entities are not found in the database.

    overrides:
        Optional id/value map that supersedes the profile selections
        (``package_set_id``, ``kernel_id``, ``toolchain_id``, ``packages``,
        ``inputs``). Used by the Plan API (M29) for wizard "what-if" plans.
    """
    override = overrides or {}
    with sync_session(db_url) as session:
        # --- distribution ---
        dist: Distribution | None = session.scalar(
            select(Distribution).where(Distribution.name == distribution_name)
        )
        if dist is None:
            raise ValueError(f"distribution not found: {distribution_name!r}")

        # --- profile ---
        profile: Profile | None = session.scalar(
            select(Profile).where(
                Profile.distribution_id == dist.id,
                Profile.name == profile_name,
            )
        )
        if profile is None:
            raise ValueError(
                f"profile not found: {profile_name!r} (distribution={distribution_name!r})"
            )
        profile_chain = _resolve_profile_chain(profile, session)
        merged_inputs = _merge_inputs(profile_chain)
        if isinstance(override.get("inputs"), dict):
            merged_inputs = {**merged_inputs, **override["inputs"]}

        def _pick(attr: str) -> str | None:
            """Override, then leaf-wins profile column across the chain."""
            if override.get(attr):
                return str(override[attr])
            for chain_profile in profile_chain:
                value = getattr(chain_profile, attr, None)
                if value:
                    return str(value)
            return None

        # --- board & arch ---
        board: Board | None = session.scalar(select(Board).where(Board.name == board_name))
        if board is None:
            raise ValueError(f"board not found: {board_name!r}")

        arch: Architecture | None = session.scalar(
            select(Architecture).where(Architecture.id == board.arch_id)
        )
        if arch is None:
            raise ValueError(f"architecture not found for board {board_name!r}")
        arch_name: str = arch.name

        # --- toolchain ---
        toolchain_ref: ToolchainRef | None = None
        toolchain_id: str | None = None
        pinned_toolchain = _pick("toolchain_id")
        tc: Toolchain | None = None
        if pinned_toolchain:
            tc = session.get(Toolchain, pinned_toolchain)
        if tc is None:
            tc = session.scalar(select(Toolchain).where(Toolchain.arch_id == arch.id))
        if tc is not None:
            toolchain_id = tc.id
            # Prefer the most-recent verified artifact
            tc_art: ToolchainArtifact | None = session.scalar(
                select(ToolchainArtifact)
                .where(ToolchainArtifact.toolchain_id == tc.id)
                .order_by(ToolchainArtifact.verified_at.desc())
            )
            toolchain_ref = ToolchainRef(
                id=tc.id,
                name=tc.name,
                arch=arch_name,
                version=tc.version,
                artifact_id=tc_art.artifact_id if tc_art else None,
            )

        # --- kernel ---
        kernel_ref: KernelRef | None = None
        kernel_id: str | None = None
        pinned_kernel = _pick("kernel_id")
        kernel: Kernel | None = None
        if pinned_kernel:
            kernel = session.get(Kernel, pinned_kernel)
        if kernel is None:
            kernel = session.scalar(
                select(Kernel).where(
                    Kernel.arch_id == arch.id,
                    Kernel.board_id == board.id,
                )
            )
        if kernel is None:
            # Fall back: any kernel for this arch
            kernel = session.scalar(select(Kernel).where(Kernel.arch_id == arch.id))
        if kernel is not None:
            kernel_id = kernel.id
            kc: KernelConfig | None = session.scalar(
                select(KernelConfig).where(
                    KernelConfig.kernel_id == kernel.id,
                    KernelConfig.board_id == board.id,
                )
            )
            kernel_ref = KernelRef(
                id=kernel.id,
                name=kernel.name,
                version=kernel.version,
                artifact_id=kc.config_artifact_id if kc else None,
            )

        # --- packages ---
        # Package selection is profile-driven (M27, closes G-02):
        #   1. an explicit profile package_set  → expand its members
        #   2. a "packages" list in merged profile inputs → those packages
        #   3. otherwise every package version for the arch (legacy default)
        package_refs: list[PackageRef] = []
        pkg_ver_ids: list[str] = []
        pinned_set = _pick("package_set_id")
        inputs_packages = override.get("packages")
        if inputs_packages is None:
            inputs_packages = merged_inputs.get("packages")
        if pinned_set:
            pvs = _packages_from_set(session, pinned_set, arch.id)
        elif isinstance(inputs_packages, list):
            pvs = _packages_by_name(session, [str(n) for n in inputs_packages], arch.id)
        else:
            pvs = list(
                session.scalars(
                    select(PackageVersion).where(PackageVersion.arch_id == arch.id)
                ).all()
            )

        pkg_map: dict[str, str] = {p.id: p.name for p in session.scalars(select(Package)).all()}
        for pv in pvs:
            pkg_name = pkg_map.get(pv.package_id, pv.package_id)
            status = pv.status if pv.artifact_id else "missing"
            package_refs.append(
                PackageRef(
                    name=pkg_name,
                    version=pv.version,
                    arch=arch_name,
                    status=status,
                    artifact_id=pv.artifact_id,
                    package_version_id=pv.id,
                )
            )
            pkg_ver_ids.append(pv.id)

        # --- firmware ---
        firmware_refs: list[FirmwareRef] = []
        fw_blobs = session.scalars(
            select(FirmwareBlob).where(FirmwareBlob.board_id == board.id)
        ).all()
        for fw in fw_blobs:
            firmware_refs.append(
                FirmwareRef(
                    filename=fw.filename,
                    placement=fw.placement,
                    required=fw.required,
                    artifact_id=fw.artifact_id,
                )
            )

        # --- overlays ---
        overlay_refs: list[OverlayRef] = []
        overlay_ids: list[str] = []
        overlays = session.scalars(
            select(Overlay).where(
                (Overlay.distribution_id == dist.id)
                | (Overlay.profile_id.in_([p.id for p in profile_chain]))
                | (Overlay.board_id == board.id)
            )
        ).all()
        for ov in overlays:
            overlay_refs.append(OverlayRef(name=ov.name, artifact_id=ov.artifact_id))
            overlay_ids.append(ov.id)

        # --- scripts ---
        script_refs: list[ScriptRef] = []
        script_ids: list[str] = []
        scripts = session.scalars(select(Script)).all()
        for sc in scripts:
            script_refs.append(
                ScriptRef(
                    name=sc.name,
                    hook=sc.hook,
                    artifact_id=sc.content_artifact_id,
                )
            )
            script_ids.append(sc.id)

        # --- partition layout ---
        layout_ref: PartitionLayoutRef | None = None
        pl: PartitionLayout | None = session.scalar(
            select(PartitionLayout).where(PartitionLayout.board_id == board.id)
        )
        if pl is not None:
            layout_ref = PartitionLayoutRef(
                id=pl.id,
                name=pl.name,
                layout_json=pl.layout_json,
            )

    # --- resolution hash ---
    hash_payload: dict[str, Any] = {
        "distribution_id": dist.id,
        "profile_id": profile.id,
        "board_id": board.id,
        "arch_id": arch.id,
        "toolchain_id": toolchain_id,
        "kernel_id": kernel_id,
        "package_version_ids": sorted(pkg_ver_ids),
        "firmware_blob_ids": sorted(fw.artifact_id or "" for fw in firmware_refs),
        "overlay_ids": sorted(overlay_ids),
        "script_ids": sorted(script_ids),
        "profile_inputs": merged_inputs,
    }
    resolution_hash = _compute_resolution_hash(hash_payload)

    # --- missing artifacts ---
    missing: list[str] = []
    # Report toolchain as missing only when kernel needs to be built with it
    if (
        toolchain_ref is not None
        and toolchain_ref.artifact_id is None
        and kernel_ref is not None
        and kernel_ref.artifact_id is None
    ):
        missing.append(f"toolchain:{toolchain_ref.name}")
    if kernel_ref is not None and kernel_ref.artifact_id is None:
        missing.append(f"kernel:{kernel_ref.name}")
    for pkg in package_refs:
        if pkg.artifact_id is None:
            missing.append(f"package:{pkg.name}:{pkg.version}:{pkg.arch}")
    for fw_ref in firmware_refs:
        if fw_ref.required and fw_ref.artifact_id is None:
            missing.append(f"firmware:{fw_ref.filename}")

    # --- required jobs ---
    required_jobs: list[str] = []
    # toolchain is only needed when the kernel must be built
    if (
        toolchain_ref is not None
        and toolchain_ref.artifact_id is None
        and kernel_ref is not None
        and kernel_ref.artifact_id is None
    ):
        required_jobs.append("toolchain.fetch")
    if kernel_ref is not None and kernel_ref.artifact_id is None:
        required_jobs.append(f"kernel.build:{kernel_ref.name}")
    for pkg in package_refs:
        if pkg.artifact_id is None:
            required_jobs.append(f"package.build:{pkg.name}")
    required_jobs.append("rootfs.compose")
    required_jobs.append("image.compose")

    upstream_rootfs_url: str | None = (board.metadata_json or {}).get("upstream_rootfs_url")

    return BuildPlan(
        distribution=distribution_name,
        profile=profile_name,
        board=board_name,
        arch=arch_name,
        resolution_hash=resolution_hash,
        distribution_id=dist.id,
        profile_id=profile.id,
        board_id=board.id,
        arch_id=arch.id,
        toolchain=toolchain_ref,
        kernel=kernel_ref,
        packages=package_refs,
        firmware=firmware_refs,
        overlays=overlay_refs,
        scripts=script_refs,
        partition_layout=layout_ref,
        upstream_rootfs_url=upstream_rootfs_url,
        missing_artifacts=missing,
        required_jobs=required_jobs,
    )
