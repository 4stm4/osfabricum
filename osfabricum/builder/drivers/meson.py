"""Meson build driver (M8).

Default commands:

* **configure** — ``meson setup _build --prefix=/usr``
* **build**     — ``ninja -C _build``
* **install**   — ``DESTDIR=${DESTDIR} ninja -C _build install``
"""

from __future__ import annotations

from osfabricum.builder.context import BuildContext
from osfabricum.builder.drivers.base import BuildDriver, _run_cmd

_SENTINEL = object()


class MesonDriver(BuildDriver):
    """Meson/Ninja driver — build tree in ``_build/`` subdirectory."""

    name = "meson"

    default_configure_cmd: str = "meson setup _build --prefix=/usr"
    default_build_cmd: str = "ninja -C _build"
    default_install_cmd: str = "DESTDIR=${DESTDIR} ninja -C _build install"

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
        self._run_phase("prepare", ctx)

    def configure(self, ctx: BuildContext) -> None:
        self._run_phase("configure", ctx, default=self.default_configure_cmd)

    def build(self, ctx: BuildContext) -> None:
        self._run_phase("build", ctx, default=self.default_build_cmd)

    def install(self, ctx: BuildContext) -> None:
        self._run_phase("install", ctx, default=self.default_install_cmd)
