"""Rust Cargo build driver (M8).

Default commands:

* **configure** — *(no-op by default)*
* **build**     — ``cargo build --release``
* **install**   — ``cargo install --path . --root ${DESTDIR}/usr --no-track``

Override any phase by supplying a list under the matching key in
``steps_json``.  Set the key to ``[]`` to skip the phase entirely.
"""

from __future__ import annotations

from osfabricum.builder.context import BuildContext
from osfabricum.builder.drivers.base import BuildDriver, _run_cmd

_SENTINEL = object()


class CargoDriver(BuildDriver):
    """Cargo driver for Rust projects."""

    name = "cargo"

    default_build_cmd: str = "cargo build --release"
    default_install_cmd: str = "cargo install --path . --root ${DESTDIR}/usr --no-track"

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
        # No default configure step for Cargo projects.
        self._run_phase("configure", ctx)

    def build(self, ctx: BuildContext) -> None:
        self._run_phase("build", ctx, default=self.default_build_cmd)

    def install(self, ctx: BuildContext) -> None:
        self._run_phase("install", ctx, default=self.default_install_cmd)
