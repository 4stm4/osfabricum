"""Business logic for M63 — Importers from Competitors / Existing Systems."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osfabricum.db.models import ImportJob, ImportKind, ImportReport, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_IMPORT_KINDS: frozenset[str] = frozenset(
    {"buildroot", "openwrt", "yocto", "debian", "alpine",
     "nixos", "rootfs", "image", "kconfig"}
)
VALID_JOB_STATUSES: frozenset[str] = frozenset({"pending", "running", "done", "failed"})


def list_import_kinds(session: "Session") -> list[ImportKind]:
    return list(
        session.scalars(select(ImportKind).order_by(ImportKind.display_order)).all()
    )


def create_import_job(
    session: "Session",
    import_kind: str,
    source_data: str | None = None,
    source_filename: str | None = None,
) -> ImportJob:
    if import_kind not in VALID_IMPORT_KINDS:
        raise ValueError(
            f"Invalid import_kind {import_kind!r}. Valid: {sorted(VALID_IMPORT_KINDS)}"
        )
    job = ImportJob(
        id=_uuid(), import_kind=import_kind,
        source_data=source_data, source_filename=source_filename,
        status="pending", created_at=_now(), completed_at=None,
    )
    session.add(job)
    session.flush()
    return job


def list_import_jobs(
    session: "Session",
    import_kind: str | None = None,
    status: str | None = None,
) -> list[ImportJob]:
    q = select(ImportJob).order_by(ImportJob.created_at.desc())
    if import_kind is not None:
        q = q.where(ImportJob.import_kind == import_kind)
    if status is not None:
        q = q.where(ImportJob.status == status)
    return list(session.scalars(q).all())


def get_import_job(session: "Session", job_id: str) -> ImportJob:
    job = session.get(ImportJob, job_id)
    if job is None:
        raise KeyError(f"ImportJob {job_id!r} not found")
    return job


def run_import(session: "Session", job_id: str) -> ImportReport:
    """Process an import job and produce a report."""
    job = get_import_job(session, job_id)
    job.status = "running"
    session.flush()

    source = job.source_data or ""
    mapped_items: list[str] = []
    unknown_items: list[str] = []

    if job.import_kind == "buildroot":
        for line in source.splitlines():
            line = line.strip()
            if line.startswith("BR2_PACKAGE_") and line.endswith("=y"):
                pkg = line[len("BR2_PACKAGE_"):].rstrip("=y").lower().replace("_", "-")
                mapped_items.append(pkg)
            elif line.startswith("# BR2_") and "is not set" in line:
                pass
            elif line and not line.startswith("#"):
                unknown_items.append(line)

    elif job.import_kind in ("debian", "alpine"):
        for line in source.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                mapped_items.append(line.split()[0])

    elif job.import_kind == "kconfig":
        for line in source.splitlines():
            line = line.strip()
            if line.startswith("CONFIG_") and "=y" in line:
                key = line.split("=")[0]
                mapped_items.append(key)

    else:
        for line in source.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                mapped_items.append(line)

    lines = [
        f"# OSFabricum Import Report — {job.import_kind}",
        f"# Job: {job.id}",
        f"# Source: {job.source_filename or '(inline)'}",
        "",
        "[summary]",
        f"mapped  = {len(mapped_items)}",
        f"unknown = {len(unknown_items)}",
    ]
    if mapped_items:
        lines.extend(["", "[mapped]"])
        for item in mapped_items[:50]:
            lines.append(f"  - {item}")
        if len(mapped_items) > 50:
            lines.append(f"  ... and {len(mapped_items) - 50} more")
    if unknown_items:
        lines.extend(["", "[unknown]"])
        for item in unknown_items[:20]:
            lines.append(f"  - {item}")

    lines.extend([
        "",
        "[next_steps]",
        "review  = Open the draft profile to verify mapped items",
        "edit    = Adjust mappings for unknown items",
        "trust   = Do not auto-trust imported values — review security settings",
    ])

    report_text = "\n".join(lines) + "\n"
    report = ImportReport(
        id=_uuid(), import_job_id=job_id,
        mapped_count=len(mapped_items),
        unknown_count=len(unknown_items),
        report_text=report_text,
        draft_profile_id=None,
        created_at=_now(),
    )
    session.add(report)
    job.status = "done"
    job.completed_at = _now()
    session.flush()
    return report


def get_import_report(session: "Session", job_id: str) -> ImportReport | None:
    return session.scalars(
        select(ImportReport)
        .where(ImportReport.import_job_id == job_id)
        .order_by(ImportReport.created_at.desc())
    ).first()
