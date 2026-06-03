"""Build dispatch (M29): create builds, queue them, execute on a worker.

``create_build`` resolves the plan, creates a ``Build`` row (status ``queued``),
records the request + plan as events, and enqueues a ``build.run`` job onto the
pyjobkit queue. A worker with the registered handler claims it and runs the
pipeline via :func:`run_queued_build` — so the build executes off the
in-process path, asynchronously (G-03).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from osfabricum.db.models import Build, Distribution, Profile
from osfabricum.db.session import sync_session
from osfabricum.orchestrator.plan import resolve_override_ids, resolve_plan_request
from osfabricum.pipeline.coordinator import PipelineSpec, run_pipeline
from osfabricum.pipeline.record import get_build, list_build_events, log_build_event
from osfabricum.queue.backend import JobBackend, JobView
from osfabricum.queue.worker import WorkerLoop

BUILD_JOB_KIND = "build.run"

_DEFAULT_STORE_ROOT = "/var/lib/osfabricum/store"


def create_build(
    *,
    distribution: str,
    profile: str,
    board: str,
    store_root: str | None = None,
    overrides: dict[str, Any] | None = None,
    db_url: str | None = None,
    enqueue: bool = True,
) -> dict[str, Any]:
    """Resolve, create a queued Build, record the plan, and enqueue ``build.run``."""
    plan = resolve_plan_request(
        distribution=distribution,
        profile=profile,
        board=board,
        overrides=overrides,
        db_url=db_url,
    )
    with sync_session(db_url) as s:
        build = Build(
            distribution_id=plan["distribution_id"],
            profile_id=plan["profile_id"],
            board_id=plan["board_id"],
            resolution_hash=plan["resolution_hash"],
            status="queued",
        )
        s.add(build)
        s.commit()
        s.refresh(build)
        build_id = build.id

    log_build_event(
        build_id,
        "build.request",
        {
            "distribution": distribution,
            "profile": profile,
            "board": board,
            "overrides": overrides,
            "store_root": store_root,
        },
        db_url=db_url,
    )
    log_build_event(
        build_id,
        "build.plan",
        {
            "resolution_hash": plan["resolution_hash"],
            "required_jobs": plan["required_jobs"],
            "missing_artifacts": plan["missing_artifacts"],
        },
        db_url=db_url,
    )

    job_id: str | None = None
    if enqueue:
        job_id = JobBackend(db_url).enqueue(
            BUILD_JOB_KIND,
            payload={
                "build_id": build_id,
                "distribution": distribution,
                "profile": profile,
                "board": board,
                "overrides": overrides,
                "store_root": store_root,
            },
            required_tags=[f"arch:{plan['arch']}"],
        )
        log_build_event(build_id, "build.queued", {"job_id": job_id}, db_url=db_url)

    return {
        "build_id": build_id,
        "status": "queued",
        "resolution_hash": plan["resolution_hash"],
        "arch": plan["arch"],
        "required_jobs": plan["required_jobs"],
        "job_id": job_id,
    }


def run_queued_build(
    payload: dict[str, Any], *, db_url: str | None = None, store_root: str | None = None
) -> dict[str, Any]:
    """Executor body: run the pipeline for a queued build."""
    build_id = payload["build_id"]
    root = Path(payload.get("store_root") or store_root or _DEFAULT_STORE_ROOT)
    id_overrides = resolve_override_ids(payload.get("overrides"), payload["distribution"], db_url)
    spec = PipelineSpec(
        distribution=payload["distribution"],
        profile=payload["profile"],
        board=payload["board"],
        store_root=root,
        db_url=db_url,
        build_id=build_id,
        overrides=id_overrides or None,
    )
    result = run_pipeline(spec)
    return {
        "build_id": build_id,
        "success": result.success,
        "image_artifact_id": result.image_artifact_id,
        "error": result.error,
    }


def register_build_handler(
    loop: WorkerLoop, *, db_url: str | None = None, store_root: str | None = None
) -> None:
    """Register the ``build.run`` handler on *loop* (called by the worker)."""

    def _handler(job: JobView) -> None:
        run_queued_build(job.payload, db_url=db_url, store_root=store_root)

    loop.register(BUILD_JOB_KIND, _handler)


def _latest_request(build_id: str, db_url: str | None) -> dict[str, Any]:
    for event in reversed(list_build_events(build_id, db_url=db_url)):
        if event.event_type == "build.request":
            return dict(event.payload_json or {})
    raise ValueError(f"no build.request recorded for build {build_id!r}")


def rebuild(build_id: str, *, db_url: str | None = None, enqueue: bool = True) -> dict[str, Any]:
    """Create a new build from a previous build's recorded request."""
    req = _latest_request(build_id, db_url)
    return create_build(
        distribution=req["distribution"],
        profile=req["profile"],
        board=req["board"],
        store_root=req.get("store_root"),
        overrides=req.get("overrides"),
        db_url=db_url,
        enqueue=enqueue,
    )


def clone_build_as_profile(
    build_id: str, new_profile_name: str, *, db_url: str | None = None
) -> dict[str, Any]:
    """Capture a build's (distribution, profile) as a new profile."""
    from osfabricum import profile as profile_service  # noqa: PLC0415

    build = get_build(build_id, db_url=db_url)
    if build is None:
        raise ValueError(f"build not found: {build_id!r}")
    with sync_session(db_url) as s:
        dist = s.get(Distribution, build.distribution_id)
        prof = s.get(Profile, build.profile_id)
        dist_name = dist.name if dist is not None else None
        prof_name = prof.name if prof is not None else None
    if not dist_name or not prof_name:
        raise ValueError("build is missing its distribution/profile")
    return profile_service.clone_profile(dist_name, prof_name, new_profile_name, db_url=db_url)


def prefetch_report(
    *,
    distribution: str,
    profile: str,
    board: str,
    overrides: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    """Resolve a plan and report what would need fetching/building (no build)."""
    plan = resolve_plan_request(
        distribution=distribution,
        profile=profile,
        board=board,
        overrides=overrides,
        db_url=db_url,
    )
    prefetch_kinds = ("source.fetch", "toolchain.fetch", "package.build", "kernel.build")
    return {
        "resolution_hash": plan["resolution_hash"],
        "missing_artifacts": plan["missing_artifacts"],
        "toolchain": (plan["toolchain"] or {}).get("name") if plan["toolchain"] else None,
        "kernel": (plan["kernel"] or {}).get("name") if plan["kernel"] else None,
        "fetch_jobs": [j for j in plan["required_jobs"] if j.startswith(prefetch_kinds)],
    }
