"""Abstract base driver and shared subprocess helper (M8)."""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod

from osfabricum.builder.context import BuildContext

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _run_cmd(cmd: str | list[str], ctx: BuildContext) -> None:
    """Run *cmd* inside *ctx.work_dir* and capture output into *ctx.logs*.

    ``shell=True`` is used when *cmd* is a plain string so that recipes can
    use shell expansions like ``${DESTDIR}``.  List commands use ``shell=False``
    for explicit argv control.

    Raises :exc:`RuntimeError` if the process exits with a non-zero code.
    """
    kwargs: dict = {
        "cwd": ctx.work_dir,
        "env": ctx.env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if isinstance(cmd, str):
        proc = subprocess.run(cmd, shell=True, **kwargs)  # noqa: S602
    else:
        proc = subprocess.run(cmd, **kwargs)  # noqa: S603

    for line in (proc.stdout or "").splitlines():
        ctx.logs.append(line)

    if proc.returncode != 0:
        tail = "\n".join(ctx.logs[-20:])
        raise RuntimeError(f"command failed (exit {proc.returncode}): {cmd!r}\n{tail}")


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BuildDriver(ABC):
    """Abstract base for all build-system drivers.

    Each driver must implement the four canonical phases; phases that are
    not meaningful for a given build system may be implemented as no-ops.
    """

    #: Short identifier used in the :data:`DRIVERS` registry.
    name: str = ""

    @abstractmethod
    def prepare(self, ctx: BuildContext) -> None:
        """Apply patches, run pre-generation scripts, etc."""

    @abstractmethod
    def configure(self, ctx: BuildContext) -> None:
        """Run the configure step (``./configure``, ``cmake``, ``meson setup``, …)."""

    @abstractmethod
    def build(self, ctx: BuildContext) -> None:
        """Compile / link the project."""

    @abstractmethod
    def install(self, ctx: BuildContext) -> None:
        """Install artefacts into ``ctx.destdir``."""
