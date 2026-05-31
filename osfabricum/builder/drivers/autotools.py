"""Autotools (autoconf/automake) build driver (M8).

Default commands:

* **prepare**   — ``autoreconf -fi`` (regenerate ``configure`` script)
* **configure** — ``./configure --prefix=/usr``
* **build**     — ``make``
* **install**   — ``make DESTDIR=${DESTDIR} install``
"""

from __future__ import annotations

from osfabricum.builder.context import BuildContext
from osfabricum.builder.drivers.base import BuildDriver, _run_cmd

_SENTINEL = object()


class AutotoolsDriver(BuildDriver):
    """Autoconf + Automake driver with autoreconf bootstrap."""

    name = "autotools"

    default_prepare_cmd: str = "autoreconf -fi"
    default_configure_cmd: str = "./configure --prefix=/usr"
    default_build_cmd: str = "make"
    default_install_cmd: str = "make DESTDIR=${DESTDIR} install"

    def _run_phase(
        self,
        phase: str,
        ctx: BuildContext,
        default: str | None = None,
    ) -> None:
        cmds: list[str] = ctx.steps.get(phase, _SENTINEL)  # type: ignore[arg-type]
        if cmds is _SENTINEL:
            if default is not None:
                _run_cmd(default, ctx)
        else:
            for cmd in cmds:
                _run_cmd(cmd, ctx)

    def prepare(self, ctx: BuildContext) -> None:
        self._run_phase("prepare", ctx, default=self.default_prepare_cmd)

    def configure(self, ctx: BuildContext) -> None:
        self._run_phase("configure", ctx, default=self.default_configure_cmd)

    def build(self, ctx: BuildContext) -> None:
        self._run_phase("build", ctx, default=self.default_build_cmd)

    def install(self, ctx: BuildContext) -> None:
        self._run_phase("install", ctx, default=self.default_install_cmd)
