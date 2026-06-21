"""Build Pipeline coordinator (M18).

``run_pipeline`` is the single entry point.  It:

1. Resolves the build plan (:func:`~osfabricum.resolver.resolve_plan`).
2. Creates a :class:`~osfabricum.db.models.Build` record.
3. Executes each pipeline step in order, recording
   :class:`~osfabricum.db.models.BuildJob` rows as it goes:

   * ``kernel.build``   — if the kernel artifact is missing (M10)
   * ``rootfs.base``    — always (M15, cached by store_key)
   * ``rootfs.compose`` — always (M16, with any available packages/overlays)
   * ``image.compose``  — unless *skip_image* is ``True`` (M17)

4. Updates the ``Build.status`` to ``"success"`` or ``"failed"``.
5. Returns a :class:`PipelineResult` with artifact IDs and logs.

Package build steps (``package.build``) are intentionally skipped at the
pipeline level when no ``src_dir`` is available — pre-built packages
(already in the store) are used directly.  Full source-to-binary package
builds will be dispatched as separate pyjobkit jobs in M18-extended.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import update as _sa_update

from osfabricum.composer.rootfs import RootfsComposeSpec, compose_rootfs
from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.image.composer import ImageSpec, compose_image
from osfabricum.pipeline.log import write_build_logs
from osfabricum.pipeline.record import (
    create_build,
    create_build_job,
    log_build_event,
    update_build_job,
    update_build_status,
)
from osfabricum.resolver import resolve_plan
from osfabricum.resolver.plan import BuildPlan
from osfabricum.rootfs.builder import RootfsSpec, build_base_rootfs, fetch_upstream_rootfs

# ---------------------------------------------------------------------------
# Spec & result
# ---------------------------------------------------------------------------


@dataclass
class PipelineSpec:
    """Input specification for a full pipeline run.

    Attributes
    ----------
    distribution, profile, board:
        Target triple.
    store_root:
        Artifact store root directory.
    db_url:
        SQLAlchemy database URL.
    jobs:
        Parallel ``make`` jobs for kernel compilation.
    skip_image:
        When ``True`` stop after ``rootfs.compose`` (no image assembly).
    init_system:
        Init system for the base rootfs (``"busybox"`` or ``"systemd"``).
    hostname:
        Default hostname written to ``/etc/hostname``.
    kernel_src_dir:
        Pre-extracted kernel source directory.  When provided, the HTTP
        fetch step is skipped (useful in tests).
    extra_boot_files:
        Additional ``{filename: bytes}`` to include in the boot partition.
    """

    distribution: str
    profile: str
    board: str
    store_root: Path
    db_url: str | None = None
    jobs: int = 1
    skip_image: bool = False
    init_system: str = "busybox"
    hostname: str = "osfabricum"
    kernel_src_dir: Path | None = None
    extra_boot_files: dict[str, bytes] = field(default_factory=dict)
    build_id: str | None = None
    """Use an existing Build record (created by the Build API, M29) instead of
    creating a new one. When set, the pipeline runs *that* build."""
    overrides: dict[str, Any] | None = None
    """Id-based resolver overrides (M29) applied during plan resolution."""


@dataclass
class PipelineResult:
    """Outcome of a :func:`run_pipeline` call."""

    success: bool
    build_id: str | None = None
    plan: BuildPlan | None = None
    kernel_artifact_id: str | None = None
    base_rootfs_artifact_id: str | None = None
    rootfs_artifact_id: str | None = None
    image_artifact_id: str | None = None
    steps_completed: list[str] = field(default_factory=list)
    steps_failed: list[str] = field(default_factory=list)
    error: str | None = None
    logs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step runner helpers
# ---------------------------------------------------------------------------


def _run_step(
    build_id: str,
    step_kind: str,
    fn,
    logs: list[str],
    db_url: str | None,
):
    """Run *fn()*, record a BuildJob + BuildLog lines, return result or raise."""
    job_id = create_build_job(build_id, step_kind, db_url=db_url)
    log_build_event(build_id, "step.start", {"step": step_kind}, job_id=job_id, db_url=db_url)
    logs.append(f"[pipeline] step: {step_kind}")
    try:
        result = fn()
        # Persist any logs the step produced (M19)
        step_logs: list[str] = getattr(result, "logs", [])
        if step_logs:
            write_build_logs(build_id, step_logs, job_id=job_id, db_url=db_url)
        update_build_job(job_id, "success", db_url=db_url)
        log_build_event(build_id, "step.done", {"step": step_kind}, job_id=job_id, db_url=db_url)
        return result
    except Exception as exc:
        update_build_job(job_id, "failed", db_url=db_url)
        log_build_event(
            build_id,
            "step.failed",
            {"step": step_kind, "error": str(exc)},
            job_id=job_id,
            db_url=db_url,
        )
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_pipeline(spec: PipelineSpec) -> PipelineResult:
    """Execute the full build pipeline for *spec*.

    Parameters
    ----------
    spec:
        The pipeline specification.

    Returns
    -------
    PipelineResult
        Result with artifact IDs and step history.
    """
    logs: list[str] = []
    build_id: str | None = None
    steps_completed: list[str] = []
    steps_failed: list[str] = []

    # ---- 1. Resolve plan ----
    try:
        logs.append(f"[pipeline] resolving plan: {spec.distribution}/{spec.profile} → {spec.board}")
        plan = resolve_plan(
            spec.distribution,
            spec.profile,
            spec.board,
            db_url=spec.db_url,
            overrides=spec.overrides,
        )
        logs.append(f"[pipeline] resolution_hash: {plan.resolution_hash}")
        logs.append(
            f"[pipeline] missing artifacts: {len(plan.missing_artifacts)}, "
            f"required jobs: {len(plan.required_jobs)}"
        )
    except Exception as exc:
        return PipelineResult(
            success=False,
            error=f"plan resolution failed: {exc}",
            logs=logs,
        )

    # ---- 2. Build record (reuse the API-created one, or create our own) ----
    if spec.build_id is not None:
        build_id = spec.build_id
        try:
            update_build_status(build_id, "running", db_url=spec.db_url)
            log_build_event(
                build_id, "build.start", {"plan": plan.resolution_hash}, db_url=spec.db_url
            )
            logs.append(f"[pipeline] build_id (existing): {build_id}")
        except Exception as exc:
            logs.append(f"[pipeline] WARNING: could not update Build record: {exc}")
    elif spec.db_url is not None and plan.distribution_id and plan.profile_id and plan.board_id:
        try:
            build_id = create_build(
                distribution_id=plan.distribution_id,
                profile_id=plan.profile_id,
                board_id=plan.board_id,
                resolution_hash=plan.resolution_hash,
                db_url=spec.db_url,
            )
            log_build_event(
                build_id,
                "build.start",
                {"plan": plan.resolution_hash},
                db_url=spec.db_url,
            )
            logs.append(f"[pipeline] build_id: {build_id}")
        except Exception as exc:
            logs.append(f"[pipeline] WARNING: could not create Build record: {exc}")

    def _fail(msg: str, step: str | None = None) -> PipelineResult:
        if step:
            steps_failed.append(step)
        if build_id is not None:
            try:
                update_build_status(build_id, "failed", db_url=spec.db_url)
                log_build_event(build_id, "build.failed", {"error": msg}, db_url=spec.db_url)
            except Exception:
                pass
        return PipelineResult(
            success=False,
            build_id=build_id,
            plan=plan,
            steps_completed=steps_completed,
            steps_failed=steps_failed,
            error=msg,
            logs=logs,
        )

    # ---- 3. Toolchain fetch + extract (if kernel build is needed) ----
    toolchain_root: Path | None = None
    _host_machine = platform.machine()
    _arch_aliases: dict[str, str] = {"aarch64": "arm64", "arm64": "aarch64"}
    _target_arch = plan.toolchain.arch if plan.toolchain is not None else ""
    _native_build = (
        _host_machine == _target_arch
        or _host_machine == _arch_aliases.get(_target_arch, "")
    )
    if plan.kernel is not None and plan.kernel.artifact_id is None and plan.toolchain is not None and not _native_build:
        logs.append(f"[pipeline] toolchain missing — fetching {plan.toolchain.name}")

        def _toolchain_step():
            from osfabricum.toolchain.fetch import fetch_and_extract_toolchain  # noqa: PLC0415

            class _R:
                logs: list[str] = []

            r = _R()
            nonlocal toolchain_root
            toolchain_root = fetch_and_extract_toolchain(
                plan.toolchain.name,  # type: ignore[union-attr]
                spec.store_root,
                db_url=spec.db_url,
            )
            logs.append(f"[pipeline] toolchain root: {toolchain_root}")
            return r

        if build_id is not None:
            try:
                _run_step(build_id, "toolchain.fetch", _toolchain_step, logs, spec.db_url)
            except Exception as exc:
                return _fail(f"toolchain fetch failed: {exc}", "toolchain.fetch")
        else:
            from osfabricum.toolchain.fetch import fetch_and_extract_toolchain  # noqa: PLC0415

            toolchain_root = fetch_and_extract_toolchain(
                plan.toolchain.name,
                spec.store_root,
                db_url=spec.db_url,
            )
    elif plan.kernel is not None and plan.kernel.artifact_id is None:
        if _native_build and plan.toolchain is not None:
            logs.append(f"[pipeline] native build ({_host_machine}→{_target_arch}) — skipping toolchain fetch, using host gcc")
        else:
            logs.append("[pipeline] no toolchain in plan — kernel build will use host PATH")

    # ---- 4. Kernel build (if missing) ----
    kernel_artifact_id: str | None = None
    kernel_modules_artifact_id: str | None = None
    kernel_dtb_artifact_ids: list[str] = []
    if plan.kernel is not None:
        if plan.kernel.artifact_id:
            kernel_artifact_id = plan.kernel.artifact_id
            logs.append(f"[pipeline] kernel cached: {plan.kernel.name}")
        else:
            logs.append(f"[pipeline] kernel missing — building {plan.kernel.name}")

            def _kernel_step():
                from osfabricum.kernel.build import build_kernel as _bk  # noqa: PLC0415

                return _bk(
                    plan.kernel.name,  # type: ignore[union-attr]
                    store_root=spec.store_root,
                    db_url=spec.db_url,
                    jobs=spec.jobs,
                    src_dir=spec.kernel_src_dir,
                    toolchain_root=toolchain_root,
                    board_name=spec.board,
                )

            if build_id is not None:
                try:
                    kr = _run_step(build_id, "kernel.build", _kernel_step, logs, spec.db_url)
                    if kr.success:
                        kernel_artifact_id = kr.image_artifact_id
                        kernel_modules_artifact_id = kr.modules_artifact_id
                        kernel_dtb_artifact_ids = list(kr.dtb_artifact_ids or [])
                        steps_completed.append("kernel.build")
                        logs.append(f"[pipeline] kernel built: {kernel_artifact_id}")
                    else:
                        return _fail(f"kernel build failed: {kr.error}", "kernel.build")
                except Exception as exc:
                    return _fail(f"kernel build raised: {exc}", "kernel.build")
            else:
                # No DB — run directly
                from osfabricum.kernel.build import build_kernel as _bk  # noqa: PLC0415

                kr = _bk(
                    plan.kernel.name,
                    store_root=spec.store_root,
                    db_url=spec.db_url,
                    jobs=spec.jobs,
                    src_dir=spec.kernel_src_dir,
                    toolchain_root=toolchain_root,
                    board_name=spec.board,
                )
                if kr.success:
                    kernel_artifact_id = kr.image_artifact_id
                    kernel_modules_artifact_id = kr.modules_artifact_id
                    kernel_dtb_artifact_ids = list(kr.dtb_artifact_ids or [])
                    steps_completed.append("kernel.build")
                else:
                    return _fail(f"kernel build failed: {kr.error}", "kernel.build")

    # ---- 4. Collect package artifacts already in store ----
    package_artifact_ids = [pkg.artifact_id for pkg in plan.packages if pkg.artifact_id is not None]
    if plan.packages:
        missing_pkgs = [p.name for p in plan.packages if p.artifact_id is None]
        if missing_pkgs:
            logs.append(
                f"[pipeline] WARNING: {len(missing_pkgs)} package(s) not yet built "
                f"(skipped): {missing_pkgs}"
            )

    # ---- 5. Collect firmware + overlay artifacts ----
    firmware_artifact_ids = [fw.artifact_id for fw in plan.firmware if fw.artifact_id is not None]
    overlay_artifact_ids = [ov.artifact_id for ov in plan.overlays if ov.artifact_id is not None]

    # ---- 6. Base rootfs ----
    base_rootfs_artifact_id: str | None = None
    rootfs_spec = RootfsSpec(
        arch=plan.arch,
        distribution=spec.distribution,
        profile=spec.profile,
        board=spec.board,
        init_system=spec.init_system,
        hostname=spec.hostname,
    )

    def _base_rootfs_step():
        if plan.upstream_rootfs_url:
            logs.append(f"[pipeline] upstream rootfs URL: {plan.upstream_rootfs_url}")
            return fetch_upstream_rootfs(
                plan.upstream_rootfs_url,
                store_root=spec.store_root,
                store_key=rootfs_spec.store_key().replace("base.tar.gz", "upstream.tar.gz"),
                arch=plan.arch,
                name=f"{spec.distribution}-{spec.board}-upstream",
                db_url=spec.db_url,
            )
        return build_base_rootfs(rootfs_spec, store_root=spec.store_root, db_url=spec.db_url)

    step_name = "rootfs.base"
    if build_id is not None:
        try:
            br = _run_step(build_id, step_name, _base_rootfs_step, logs, spec.db_url)
            if br.success:
                base_rootfs_artifact_id = br.artifact_id
                steps_completed.append(step_name)
            else:
                return _fail(f"base rootfs failed: {br.error}", step_name)
        except Exception as exc:
            return _fail(f"base rootfs raised: {exc}", step_name)
    else:
        br = _base_rootfs_step()
        if br.success:
            base_rootfs_artifact_id = br.artifact_id
            steps_completed.append(step_name)
        else:
            return _fail(f"base rootfs failed: {br.error}", step_name)

    logs.append(f"[pipeline] base rootfs: {base_rootfs_artifact_id}")

    # ---- 7. Rootfs compose ----
    rootfs_artifact_id: str | None = None
    compose_spec = RootfsComposeSpec(
        distribution=spec.distribution,
        profile=spec.profile,
        board=spec.board,
        arch=plan.arch,
        base_artifact_id=base_rootfs_artifact_id,  # type: ignore[arg-type]
        package_artifact_ids=package_artifact_ids,
        overlay_artifact_ids=overlay_artifact_ids,
        init_system=spec.init_system,
    )

    def _compose_rootfs_step():
        return compose_rootfs(compose_spec, store_root=spec.store_root, db_url=spec.db_url)

    step_name = "rootfs.compose"
    if build_id is not None:
        try:
            cr = _run_step(build_id, step_name, _compose_rootfs_step, logs, spec.db_url)
            if cr.success:
                rootfs_artifact_id = cr.artifact_id
                steps_completed.append(step_name)
            else:
                return _fail(f"rootfs compose failed: {cr.error}", step_name)
        except Exception as exc:
            return _fail(f"rootfs compose raised: {exc}", step_name)
    else:
        cr = _compose_rootfs_step()
        if cr.success:
            rootfs_artifact_id = cr.artifact_id
            steps_completed.append(step_name)
        else:
            return _fail(f"rootfs compose failed: {cr.error}", step_name)

    logs.append(f"[pipeline] composed rootfs: {rootfs_artifact_id}")

    # ---- 8. Image compose ----
    image_artifact_id: str | None = None
    if not spec.skip_image:
        image_spec = ImageSpec(
            distribution=spec.distribution,
            profile=spec.profile,
            board=spec.board,
            arch=plan.arch,
            rootfs_artifact_id=rootfs_artifact_id,  # type: ignore[arg-type]
            kernel_artifact_id=kernel_artifact_id,
            firmware_artifact_ids=firmware_artifact_ids,
            extra_boot_files=spec.extra_boot_files,
            boot_size_mb=96,
            rootfs_size_mb=512,
        )

        def _compose_image_step():
            return compose_image(image_spec, store_root=spec.store_root, db_url=spec.db_url)

        step_name = "image.compose"
        if build_id is not None:
            try:
                ir = _run_step(build_id, step_name, _compose_image_step, logs, spec.db_url)
                if ir.success:
                    image_artifact_id = ir.artifact_id
                    steps_completed.append(step_name)
                else:
                    return _fail(f"image compose failed: {ir.error}", step_name)
            except Exception as exc:
                return _fail(f"image compose raised: {exc}", step_name)
        else:
            ir = _compose_image_step()
            if ir.success:
                image_artifact_id = ir.artifact_id
                steps_completed.append(step_name)
            else:
                return _fail(f"image compose failed: {ir.error}", step_name)

        logs.append(f"[pipeline] image: {image_artifact_id}")

    # ---- 9. Mark build success ----
    if build_id is not None:
        try:
            update_build_status(build_id, "success", db_url=spec.db_url)
            log_build_event(build_id, "build.success", {}, db_url=spec.db_url)
        except Exception:
            pass

    # ---- 10. Link produced artifacts to this build ----
    if build_id is not None and spec.db_url is not None:
        link_ids = [
            x for x in [
                kernel_artifact_id, kernel_modules_artifact_id,
                *kernel_dtb_artifact_ids,
                base_rootfs_artifact_id, rootfs_artifact_id, image_artifact_id,
            ]
            if x is not None
        ]
        if link_ids:
            try:
                with sync_session(spec.db_url) as _s:
                    _s.execute(
                        _sa_update(Artifact)
                        .where(Artifact.id.in_(link_ids))
                        .values(producer_build_id=build_id)
                    )
                    _s.commit()
            except Exception:
                pass

    logs.append(f"[pipeline] DONE — steps: {steps_completed}")

    return PipelineResult(
        success=True,
        build_id=build_id,
        plan=plan,
        kernel_artifact_id=kernel_artifact_id,
        base_rootfs_artifact_id=base_rootfs_artifact_id,
        rootfs_artifact_id=rootfs_artifact_id,
        image_artifact_id=image_artifact_id,
        steps_completed=steps_completed,
        logs=logs,
    )
