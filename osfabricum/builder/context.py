"""Shared build context passed between driver phases (M8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BuildContext:
    """All mutable state shared between prepare / configure / build / install phases."""

    #: Root of the (already extracted) source tree.
    src_dir: Path

    #: Temporary working directory for intermediate artefacts.
    work_dir: Path

    #: Staging root — drivers must install here (honouring DESTDIR).
    destdir: Path

    #: Process environment injected into every subprocess call.
    env: dict[str, str] = field(default_factory=dict)

    #: Parsed ``steps_json`` from the :class:`~osfabricum.db.models.BuildRecipe`.
    steps: dict[str, Any] = field(default_factory=dict)

    #: Lines appended by :func:`_run_cmd` and available to the caller.
    logs: list[str] = field(default_factory=list)
