"""Build orchestration (M29): Plan write API + Build API + queue dispatch.

The Plan side resolves build plans with name-based overrides (no building).
The Build side creates a Build record, stores the plan, and dispatches a
``build.run`` job onto the pyjobkit queue; a worker executes it via the
pipeline. This is what moves builds off the in-process-only path (G-03).
"""

from __future__ import annotations

from osfabricum.orchestrator.build import (
    BUILD_JOB_KIND,
    clone_build_as_profile,
    create_build,
    prefetch_report,
    rebuild,
    register_build_handler,
    run_queued_build,
)
from osfabricum.orchestrator.plan import diff_plans, resolve_plan_request, validate_plan

__all__ = [
    "BUILD_JOB_KIND",
    "clone_build_as_profile",
    "create_build",
    "diff_plans",
    "prefetch_report",
    "rebuild",
    "register_build_handler",
    "resolve_plan_request",
    "run_queued_build",
    "validate_plan",
]
