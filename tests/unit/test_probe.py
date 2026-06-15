"""Unit tests for M53 — Hardware Probe Import designer."""

from __future__ import annotations

import pytest

from osfabricum import probe
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_probe_source_kinds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/test_probe.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import Session

    with Session(engine) as s:
        seed_probe_source_kinds(s)
        s.commit()

    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session

    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# Source kinds
# ---------------------------------------------------------------------------


def test_source_kinds_seeded(session):
    kinds = probe.list_probe_source_kinds(session)
    assert len(kinds) == 5


def test_source_kinds_ordered(session):
    kinds = probe.list_probe_source_kinds(session)
    orders = [k.display_order for k in kinds]
    assert orders == sorted(orders)


def test_source_kinds_have_expected_values(session):
    kinds = probe.list_probe_source_kinds(session)
    names = {k.kind for k in kinds}
    assert names == {"udev", "dmidecode", "lshw", "sysfs", "manual"}


def test_source_kinds_have_labels(session):
    kinds = probe.list_probe_source_kinds(session)
    for k in kinds:
        assert k.label
        assert k.description


# ---------------------------------------------------------------------------
# Basic import
# ---------------------------------------------------------------------------


def test_import_minimal_probe(session):
    p = probe.import_hardware_probe(session, "node-01", {})
    session.commit()
    assert p.id
    assert p.name == "node-01"
    assert p.probe_source == "manual"
    assert p.content_hash.startswith("sha256:")


def test_import_with_cpu_arch(session):
    p = probe.import_hardware_probe(session, "arm-node", {"cpu_arch": "aarch64"})
    session.commit()
    assert p.cpu_arch == "aarch64"


def test_import_with_cpu_model(session):
    p = probe.import_hardware_probe(session, "rpi4", {"cpu_model": "Cortex-A72"})
    session.commit()
    assert p.cpu_model == "Cortex-A72"


def test_import_with_mem_mb(session):
    p = probe.import_hardware_probe(session, "rpi4", {"mem_mb": 4096})
    session.commit()
    assert p.mem_mb == 4096


def test_import_alias_arch(session):
    p = probe.import_hardware_probe(session, "n1", {"arch": "x86_64"})
    session.commit()
    assert p.cpu_arch == "x86_64"


def test_import_alias_cpu(session):
    p = probe.import_hardware_probe(session, "n1", {"cpu": "Intel Xeon"})
    session.commit()
    assert p.cpu_model == "Intel Xeon"


def test_import_alias_mem(session):
    p = probe.import_hardware_probe(session, "n1", {"memory_mb": 2048})
    session.commit()
    assert p.mem_mb == 2048


def test_import_alias_ram(session):
    p = probe.import_hardware_probe(session, "n1", {"ram_mb": 512})
    session.commit()
    assert p.mem_mb == 512


def test_import_probe_source_lshw(session):
    p = probe.import_hardware_probe(session, "n1", {"cpu_arch": "x86_64"}, probe_source="lshw")
    session.commit()
    assert p.probe_source == "lshw"


def test_import_probe_source_udev(session):
    p = probe.import_hardware_probe(session, "n1", {}, probe_source="udev")
    assert p.probe_source == "udev"


def test_import_invalid_source_raises(session):
    with pytest.raises(ValueError, match="Invalid probe_source"):
        probe.import_hardware_probe(session, "n1", {}, probe_source="bad")


def test_import_sets_probed_at(session):
    p = probe.import_hardware_probe(session, "n1", {})
    assert p.probed_at is not None


def test_import_sets_created_at(session):
    p = probe.import_hardware_probe(session, "n1", {})
    assert p.created_at is not None


def test_import_stores_raw_json(session):
    data = {"cpu_arch": "aarch64", "extra_key": "value"}
    p = probe.import_hardware_probe(session, "n1", data)
    import json
    stored = json.loads(p.raw_probe_json)
    assert stored["cpu_arch"] == "aarch64"


# ---------------------------------------------------------------------------
# Arch normalisation in board hints
# ---------------------------------------------------------------------------


def test_hints_normalise_amd64_to_x86_64(session):
    p = probe.import_hardware_probe(session, "n1", {"cpu_arch": "amd64"})
    assert "suggested_arch = x86_64" in p.rendered_board_hints


def test_hints_normalise_arm64_to_aarch64(session):
    p = probe.import_hardware_probe(session, "n1", {"cpu_arch": "arm64"})
    assert "suggested_arch = aarch64" in p.rendered_board_hints


def test_hints_normalise_armhf_to_armv7hf(session):
    p = probe.import_hardware_probe(session, "n1", {"cpu_arch": "armhf"})
    assert "suggested_arch = armv7hf" in p.rendered_board_hints


def test_hints_normalise_riscv64(session):
    p = probe.import_hardware_probe(session, "n1", {"cpu_arch": "riscv64"})
    assert "suggested_arch = riscv64" in p.rendered_board_hints


def test_hints_no_arch_no_suggested(session):
    p = probe.import_hardware_probe(session, "n1", {})
    assert "suggested_arch" not in p.rendered_board_hints


# ---------------------------------------------------------------------------
# Memory class in board hints
# ---------------------------------------------------------------------------


def test_hints_memory_class_high(session):
    p = probe.import_hardware_probe(session, "n1", {"mem_mb": 8192})
    assert "memory_class = high" in p.rendered_board_hints


def test_hints_memory_class_medium(session):
    p = probe.import_hardware_probe(session, "n1", {"mem_mb": 2048})
    assert "memory_class = medium" in p.rendered_board_hints


def test_hints_memory_class_low(session):
    p = probe.import_hardware_probe(session, "n1", {"mem_mb": 512})
    assert "memory_class = low" in p.rendered_board_hints


def test_hints_memory_boundary_4096_is_high(session):
    p = probe.import_hardware_probe(session, "n1", {"mem_mb": 4096})
    assert "memory_class = high" in p.rendered_board_hints


def test_hints_memory_boundary_1024_is_medium(session):
    p = probe.import_hardware_probe(session, "n1", {"mem_mb": 1024})
    assert "memory_class = medium" in p.rendered_board_hints


def test_hints_no_mem_no_memory_class(session):
    p = probe.import_hardware_probe(session, "n1", {})
    assert "memory_class" not in p.rendered_board_hints


# ---------------------------------------------------------------------------
# Board hints structure
# ---------------------------------------------------------------------------


def test_hints_contains_detected_hardware_section(session):
    p = probe.import_hardware_probe(session, "n1", {"cpu_arch": "aarch64"})
    assert "[detected_hardware]" in p.rendered_board_hints


def test_hints_contains_board_hints_section(session):
    p = probe.import_hardware_probe(session, "n1", {})
    assert "[board_hints]" in p.rendered_board_hints


def test_hints_extra_attributes_section(session):
    p = probe.import_hardware_probe(session, "n1", {"board": "RPi4", "gpu": "VideoCore"})
    assert "[extra_attributes]" in p.rendered_board_hints
    assert "board = RPi4" in p.rendered_board_hints


# ---------------------------------------------------------------------------
# List / get / delete
# ---------------------------------------------------------------------------


def test_list_probes_empty(session):
    assert probe.list_hardware_probes(session) == []


def test_list_probes_returns_all(session):
    probe.import_hardware_probe(session, "a", {})
    probe.import_hardware_probe(session, "b", {})
    session.commit()
    all_probes = probe.list_hardware_probes(session)
    assert len(all_probes) == 2


def test_list_probes_sorted_by_name(session):
    probe.import_hardware_probe(session, "z-node", {})
    probe.import_hardware_probe(session, "a-node", {})
    session.commit()
    names = [p.name for p in probe.list_hardware_probes(session)]
    assert names == sorted(names)


def test_get_probe_returns_correct(session):
    p = probe.import_hardware_probe(session, "target", {"cpu_arch": "x86_64"})
    session.commit()
    fetched = probe.get_hardware_probe(session, p.id)
    assert fetched.id == p.id
    assert fetched.cpu_arch == "x86_64"


def test_get_probe_not_found_raises(session):
    with pytest.raises(KeyError):
        probe.get_hardware_probe(session, "nonexistent-id")


def test_delete_probe(session):
    p = probe.import_hardware_probe(session, "temp", {})
    session.commit()
    probe.delete_hardware_probe(session, p.id)
    session.commit()
    assert probe.list_hardware_probes(session) == []


def test_delete_probe_not_found_raises(session):
    with pytest.raises(KeyError):
        probe.delete_hardware_probe(session, "ghost")


# ---------------------------------------------------------------------------
# Hash determinism
# ---------------------------------------------------------------------------


def test_hash_deterministic_same_data(session):
    p1 = probe.import_hardware_probe(session, "same-node", {"cpu_arch": "aarch64", "mem_mb": 4096})
    p2 = probe.import_hardware_probe(session, "same-node", {"cpu_arch": "aarch64", "mem_mb": 4096})
    assert p1.content_hash == p2.content_hash


def test_hash_differs_for_different_arch(session):
    p1 = probe.import_hardware_probe(session, "a", {"cpu_arch": "x86_64"})
    p2 = probe.import_hardware_probe(session, "b", {"cpu_arch": "aarch64"})
    assert p1.content_hash != p2.content_hash
