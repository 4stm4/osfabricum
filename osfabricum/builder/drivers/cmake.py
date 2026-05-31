"""CMake build driver (M8).

Default commands:

* **configure** — ``cmake -B _build -DCMAKE_INSTALL_PREFIX=/usr``
* **build**     — ``cmake --build _build``
* **install**   — ``cmake --install _build --prefix ${DESTDIR}/usr``
"""

from __future__ import annotations

from osfabricum.builder.context import BuildContext
from osfabricum.builder.drivers.base import BuildDriver, _run_cmd

_SENTINEL = object()


class CMakeDriver(BuildDriver):
    """CMake driver — out-of-source build in ``_build/`` subdirectory."""

    name = "cmake"

    default_configure_cmd: str = "cmake -B _build -DCMAKE_INSTALL_PREFIX=/usr"
    default_build_cmd: str = "cmake --build _build"
    default_install_cmd: str = "cmake --install _build --prefix ${DESTDIR}/usr"

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
