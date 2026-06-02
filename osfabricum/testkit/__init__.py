"""Image test runner (M22) — QEMU boot, suites, healthchecks."""

from osfabricum.testkit.qemu import BootResult, QemuConfig, boot_capture, build_qemu_command
from osfabricum.testkit.runner import (
    CaseResult,
    SuiteResult,
    evaluate_case,
    run_image_test,
    run_suite,
)
from osfabricum.testkit.suites import (
    BUILTIN_SUITES,
    TestCase,
    TestSuite,
    get_suite,
    list_suites,
)

__all__ = [
    "BUILTIN_SUITES",
    "BootResult",
    "CaseResult",
    "QemuConfig",
    "SuiteResult",
    "TestCase",
    "TestSuite",
    "boot_capture",
    "build_qemu_command",
    "evaluate_case",
    "get_suite",
    "list_suites",
    "run_image_test",
    "run_suite",
]
