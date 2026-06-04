"""Image test suite definitions (M22).

A *test suite* is a named, ordered collection of *test cases*.  Each case
has a ``kind`` that determines how it is evaluated against a booted image:

* ``boot``    — the serial console transcript must contain ``marker``.
* ``log``     — the transcript must contain (or, with ``negate``, not
  contain) ``pattern``.
* ``service`` — a service-start marker (``Starting <name>`` or the case's
  ``pattern``) must appear in the transcript.
* ``command`` — a command is run via an executor callback; its exit code
  must equal ``expect_exit`` and, if given, its output must contain
  ``expect_output``.

The default executor (no SSH/agent available) marks ``command`` cases as
*skipped* rather than failing, so suites remain useful in transcript-only
(serial) mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TestCase:
    """One check within a :class:`TestSuite`."""

    # Tell pytest not to collect this dataclass as a test class.
    __test__ = False

    name: str
    kind: str  # "boot" | "log" | "service" | "command"
    spec: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "spec": self.spec}


@dataclass
class TestSuite:
    """A named, ordered collection of test cases."""

    # Tell pytest not to collect this dataclass as a test class.
    __test__ = False

    name: str
    description: str
    cases: list[TestCase] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "cases": [c.to_dict() for c in self.cases],
        }


# Default boot marker emitted by a successful BusyBox/systemd boot.  The
# OSFabricum rcS script (M15) reaches the login prompt; we also accept the
# common kernel "Run /sbin/init" / login markers.
DEFAULT_BOOT_MARKERS: tuple[str, ...] = (
    "login:",
    "Please press Enter to activate this console",
    "OSFabricum",
    "Welcome to",
)


# ---------------------------------------------------------------------------
# Built-in suites
# ---------------------------------------------------------------------------

_SMOKE = TestSuite(
    name="smoke",
    description="Minimal boot smoke test — image boots to a login prompt.",
    cases=[
        TestCase(
            name="boot-to-login",
            kind="boot",
            spec={"markers": list(DEFAULT_BOOT_MARKERS)},
        ),
        TestCase(
            name="no-kernel-panic",
            kind="log",
            spec={"pattern": "Kernel panic", "negate": True},
        ),
    ],
)

_SERVICES = TestSuite(
    name="services",
    description="Verify core services start during boot.",
    cases=[
        TestCase(
            name="rcS-ran",
            kind="log",
            spec={"pattern": "Starting", "negate": False},
        ),
        TestCase(
            name="no-segfault",
            kind="log",
            spec={"pattern": "segfault", "negate": True},
        ),
    ],
)

_NETWORK = TestSuite(
    name="network",
    description="Verify network bring-up and reachability (requires executor).",
    cases=[
        TestCase(
            name="loopback-up",
            kind="command",
            spec={"command": "ip link show lo", "expect_exit": 0, "expect_output": "lo"},
        ),
        TestCase(
            name="hostname-set",
            kind="command",
            spec={"command": "hostname", "expect_exit": 0},
        ),
    ],
)

#: All built-in suites keyed by name.
BUILTIN_SUITES: dict[str, TestSuite] = {s.name: s for s in (_SMOKE, _SERVICES, _NETWORK)}


def get_suite(name: str) -> TestSuite:
    """Return a built-in suite by name, or raise :class:`KeyError`."""
    if name not in BUILTIN_SUITES:
        raise KeyError(f"unknown test suite: {name!r}; available: {sorted(BUILTIN_SUITES)}")
    return BUILTIN_SUITES[name]


def list_suites() -> list[TestSuite]:
    """Return all built-in suites."""
    return list(BUILTIN_SUITES.values())
