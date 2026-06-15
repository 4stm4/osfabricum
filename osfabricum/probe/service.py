"""Business logic for M53 — Hardware Probe Import designer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from osfabricum.db.models import HardwareProbe, ProbeSourceKind, _now, _uuid

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

VALID_PROBE_SOURCES: frozenset[str] = frozenset(
    {"udev", "dmidecode", "sysfs", "lshw", "manual"}
)


def list_probe_source_kinds(session: "Session") -> list[ProbeSourceKind]:
    return list(
        session.scalars(
            select(ProbeSourceKind).order_by(ProbeSourceKind.display_order)
        ).all()
    )


def import_hardware_probe(
    session: "Session",
    name: str,
    probe_data: dict[str, Any],
    probe_source: str = "manual",
    board_id: str | None = None,
) -> HardwareProbe:
    if probe_source not in VALID_PROBE_SOURCES:
        raise ValueError(
            f"Invalid probe_source {probe_source!r}. Valid: {sorted(VALID_PROBE_SOURCES)}"
        )
    raw_json = json.dumps(probe_data, sort_keys=True)

    cpu_arch = _extract(probe_data, "cpu_arch", "arch", "architecture")
    cpu_model = _extract(probe_data, "cpu_model", "cpu", "processor")
    mem_mb = _extract_int(probe_data, "mem_mb", "memory_mb", "ram_mb")

    hints = _render_board_hints(name, probe_source, probe_data, cpu_arch, cpu_model, mem_mb)
    content_hash = "sha256:" + hashlib.sha256((raw_json + hints).encode()).hexdigest()

    now = _now()
    probe = HardwareProbe(
        id=_uuid(),
        name=name,
        board_id=board_id,
        probe_source=probe_source,
        raw_probe_json=raw_json,
        cpu_arch=cpu_arch,
        cpu_model=cpu_model,
        mem_mb=mem_mb,
        rendered_board_hints=hints,
        content_hash=content_hash,
        probed_at=datetime.utcnow(),
        created_at=now,
        updated_at=now,
    )
    session.add(probe)
    session.flush()
    return probe


def list_hardware_probes(session: "Session") -> list[HardwareProbe]:
    return list(
        session.scalars(
            select(HardwareProbe).order_by(HardwareProbe.name)
        ).all()
    )


def get_hardware_probe(session: "Session", probe_id: str) -> HardwareProbe:
    p = session.get(HardwareProbe, probe_id)
    if p is None:
        raise KeyError(f"Hardware probe {probe_id!r} not found")
    return p


def delete_hardware_probe(session: "Session", probe_id: str) -> None:
    p = get_hardware_probe(session, probe_id)
    session.delete(p)
    session.flush()


def _extract(data: dict, *keys: str) -> str | None:
    for k in keys:
        v = data.get(k)
        if v is not None:
            return str(v)
    return None


def _extract_int(data: dict, *keys: str) -> int | None:
    for k in keys:
        v = data.get(k)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def _render_board_hints(
    name: str,
    source: str,
    data: dict,
    cpu_arch: str | None,
    cpu_model: str | None,
    mem_mb: int | None,
) -> str:
    lines = [
        f"# OSFabricum Hardware Probe — {name}",
        f"# source: {source}",
        "",
        "[detected_hardware]",
    ]
    if cpu_arch:
        lines.append(f"cpu_arch = {cpu_arch}")
    if cpu_model:
        lines.append(f"cpu_model = {cpu_model}")
    if mem_mb is not None:
        lines.append(f"mem_mb = {mem_mb}")

    extra_keys = [k for k in data if k not in {"cpu_arch", "arch", "architecture",
                                                "cpu_model", "cpu", "processor",
                                                "mem_mb", "memory_mb", "ram_mb"}]
    if extra_keys:
        lines.append("")
        lines.append("[extra_attributes]")
        for k in sorted(extra_keys):
            v = data[k]
            if not isinstance(v, (dict, list)):
                lines.append(f"{k} = {v}")

    lines.append("")
    lines.append("[board_hints]")
    if cpu_arch:
        arch_map = {
            "x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64",
            "aarch64": "aarch64", "armv7": "armv7hf", "armhf": "armv7hf",
            "riscv64": "riscv64",
        }
        norm = arch_map.get(cpu_arch.lower(), cpu_arch)
        lines.append(f"suggested_arch = {norm}")
    if mem_mb is not None:
        if mem_mb >= 4096:
            lines.append("memory_class = high  # ≥4 GB")
        elif mem_mb >= 1024:
            lines.append("memory_class = medium  # 1–4 GB")
        else:
            lines.append("memory_class = low  # <1 GB")

    return "\n".join(lines) + "\n"
