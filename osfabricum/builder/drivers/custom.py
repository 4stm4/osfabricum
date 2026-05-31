"""Custom build driver — runs arbitrary shell commands per phase (M8).

Recipe ``steps_json`` format::

    {
        "prepare":   ["patch -p1 < my.patch"],
        "configure": [],
        "build":     ["make -j$(nproc)"],
        "install":   ["make DESTDIR=${DESTDIR} install"]
    }

Missing or empty phase lists are silently skipped.
"""

from __future__ import annotations

from osfabricum.builder.context import BuildContext
from osfabricum.builder.drivers.base import BuildDriver, _run_cmd


class CustomDriver(BuildDriver):
    """Executes the exact commands from ``steps_json`` for each phase."""

    name = "custom"

    def _run_phase(self, phase: str, ctx: BuildContext) -> None:
        for cmd in ctx.steps.get(phase, []):
            _run_cmd(cmd, ctx)

    def prepare(self, ctx: BuildContext) -> None:
        self._run_phase("prepare", ctx)

    def configure(self, ctx: BuildContext) -> None:
        self._run_phase("configure", ctx)

    def build(self, ctx: BuildContext) -> None:
        self._run_phase("build", ctx)

    def install(self, ctx: BuildContext) -> None:
        self._run_phase("install", ctx)
