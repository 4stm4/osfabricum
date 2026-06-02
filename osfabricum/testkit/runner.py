"""Image test runner (M22).

``run_suite``
    Boot an image under QEMU (via :func:`~osfabricum.testkit.qemu.boot_capture`)
    and evaluate every case in a :class:`~osfabricum.testkit.suites.TestSuite`
    against the captured serial transcript and an optional command executor.

``run_image_test``
    High-level: load an ``image`` artifact from the store, write it to a
    temp file, build a :class:`QemuConfig`, and run a named suite.

A *command executor* is a callable ``(command: str) -> (exit_code, output)``.
When ``None``, ``command`` cases are reported as *skipped*.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.store.layout import blob_path
from osfabricum.testkit.qemu import BootResult, QemuConfig, boot_capture
from osfabricum.testkit.suites import TestCase, TestSuite, get_suite

CommandExecutor = Callable[[str], tuple[int, str]]

# Case outcome constants
PASS = "pass"
FAIL = "fail"
SKIP = "skip"


@dataclass
class CaseResult:
    """Outcome of a single test case."""

    name: str
    kind: str
    outcome: str  # PASS | FAIL | SKIP
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in (PASS, SKIP)


@dataclass
class SuiteResult:
    """Aggregated outcome of running a whole suite."""

    suite: str
    booted: bool
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    cases: list[CaseResult] = field(default_factory=list)
    transcript: str = ""
    error: str | None = None
    logs: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.booted and self.failed == 0 and self.error is None


# ---------------------------------------------------------------------------
# Case evaluation
# ---------------------------------------------------------------------------


def evaluate_case(
    case: TestCase,
    transcript: str,
    booted: bool,
    executor: CommandExecutor | None,
) -> CaseResult:
    """Evaluate a single *case* against the boot *transcript* / *executor*."""
    if case.kind == "boot":
        markers: list[str] = case.spec.get("markers", [])
        hit = booted or any(m in transcript for m in markers)
        return CaseResult(
            name=case.name, kind=case.kind,
            outcome=PASS if hit else FAIL,
            detail="" if hit else f"no boot marker found ({markers})",
        )

    if case.kind in ("log", "service"):
        pattern: str = case.spec.get("pattern", "")
        if case.kind == "service" and not pattern:
            pattern = f"Starting {case.spec.get('service', case.name)}"
        negate: bool = bool(case.spec.get("negate", False))
        present = pattern in transcript
        ok = (not present) if negate else present
        if ok:
            return CaseResult(name=case.name, kind=case.kind, outcome=PASS)
        msg = (
            f"pattern {pattern!r} unexpectedly present"
            if negate
            else f"pattern {pattern!r} not found in transcript"
        )
        return CaseResult(name=case.name, kind=case.kind, outcome=FAIL, detail=msg)

    if case.kind == "command":
        if executor is None:
            return CaseResult(
                name=case.name, kind=case.kind, outcome=SKIP,
                detail="no command executor (serial-only run)",
            )
        command: str = case.spec.get("command", "")
        expect_exit: int = int(case.spec.get("expect_exit", 0))
        expect_output: str | None = case.spec.get("expect_output")
        exit_code, output = executor(command)
        if exit_code != expect_exit:
            return CaseResult(
                name=case.name, kind=case.kind, outcome=FAIL,
                detail=f"exit {exit_code} != expected {expect_exit}",
            )
        if expect_output is not None and expect_output not in output:
            return CaseResult(
                name=case.name, kind=case.kind, outcome=FAIL,
                detail=f"output missing {expect_output!r}",
            )
        return CaseResult(name=case.name, kind=case.kind, outcome=PASS)

    return CaseResult(
        name=case.name, kind=case.kind, outcome=FAIL,
        detail=f"unknown case kind: {case.kind!r}",
    )


# ---------------------------------------------------------------------------
# Suite runner
# ---------------------------------------------------------------------------


def run_suite(
    suite: TestSuite,
    config: QemuConfig,
    *,
    executor: CommandExecutor | None = None,
    boot_result: BootResult | None = None,
) -> SuiteResult:
    """Boot the image and run every case in *suite*.

    Parameters
    ----------
    suite:
        The test suite to run.
    config:
        QEMU configuration (image, arch, timeout, …).
    executor:
        Optional command executor for ``command`` cases.
    boot_result:
        Pre-captured :class:`BootResult` (used in tests to skip QEMU).
        When ``None`` the image is booted via
        :func:`~osfabricum.testkit.qemu.boot_capture`.
    """
    logs: list[str] = []

    # Gather boot markers from any boot cases (fall back to suite defaults)
    boot_markers: list[str] = []
    for c in suite.cases:
        if c.kind == "boot":
            boot_markers.extend(c.spec.get("markers", []))
    if not boot_markers:
        from osfabricum.testkit.suites import DEFAULT_BOOT_MARKERS  # noqa: PLC0415
        boot_markers = list(DEFAULT_BOOT_MARKERS)

    if boot_result is None:
        logs.append(f"[test] booting {config.image_path.name} under {config.qemu_binary()}")
        boot_result = boot_capture(config, boot_markers)

    if boot_result.error:
        return SuiteResult(
            suite=suite.name,
            booted=False,
            error=boot_result.error,
            transcript=boot_result.transcript,
            logs=logs,
        )

    logs.append(
        f"[test] boot {'OK' if boot_result.booted else 'FAILED'}"
        + (" (timed out)" if boot_result.timed_out else "")
    )

    result = SuiteResult(
        suite=suite.name,
        booted=boot_result.booted,
        transcript=boot_result.transcript,
        logs=logs,
    )

    for case in suite.cases:
        cr = evaluate_case(case, boot_result.transcript, boot_result.booted, executor)
        result.cases.append(cr)
        if cr.outcome == "pass":
            result.passed += 1
        elif cr.outcome == "skip":
            result.skipped += 1
        else:
            result.failed += 1
        logs.append(f"[test]   {cr.outcome.upper():4} {case.name}"
                    + (f" — {cr.detail}" if cr.detail else ""))

    return result


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------


def run_image_test(
    artifact_id: str,
    suite_name: str,
    *,
    store_root: Path,
    arch: str = "aarch64",
    timeout_s: int = 60,
    db_url: str | None = None,
    executor: CommandExecutor | None = None,
    boot_result: BootResult | None = None,
) -> SuiteResult:
    """Run a named test suite against an ``image`` artifact.

    Loads the artifact blob, writes it to a temp file (decompressing gzip),
    builds a :class:`QemuConfig`, and runs the suite.
    """
    import gzip  # noqa: PLC0415

    suite = get_suite(suite_name)

    with sync_session(db_url) as session:
        art: Artifact | None = session.scalar(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        if art is None:
            return SuiteResult(
                suite=suite_name, booted=False,
                error=f"artifact not found: {artifact_id!r}",
            )
        sha256 = art.blob_sha256
        arch = art.arch or arch

    bp = blob_path(store_root, sha256)
    if not bp.exists():
        return SuiteResult(
            suite=suite_name, booted=False,
            error=f"blob not found for artifact {artifact_id}: {bp}",
        )

    raw = bp.read_bytes()
    image_data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw

    tmp = tempfile.mkdtemp(prefix="osfab-test-")
    image_path = Path(tmp) / "image.img"
    image_path.write_bytes(image_data)

    config = QemuConfig(arch=arch, image_path=image_path, timeout_s=timeout_s)
    return run_suite(suite, config, executor=executor, boot_result=boot_result)
