"""Unit tests for M63 — Importers from Foreign Systems."""

from __future__ import annotations

import pytest

from osfabricum import importers as imp_svc
from osfabricum.db.models import Base
from osfabricum.db.seed_data import seed_import_kinds


@pytest.fixture()
def db_engine(tmp_path):
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path}/test_importers.db"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        seed_import_kinds(s)
        s.commit()
    return engine


@pytest.fixture()
def session(db_engine):
    from sqlalchemy.orm import Session
    with Session(db_engine) as s:
        yield s


# ---------------------------------------------------------------------------
# list_import_kinds
# ---------------------------------------------------------------------------

def test_list_import_kinds(session):
    kinds = imp_svc.list_import_kinds(session)
    assert len(kinds) == 9
    kind_names = {k.kind for k in kinds}
    assert "buildroot" in kind_names
    assert "debian" in kind_names
    assert "kconfig" in kind_names


# ---------------------------------------------------------------------------
# create_import_job
# ---------------------------------------------------------------------------

def test_create_job(session):
    job = imp_svc.create_import_job(session, import_kind="buildroot", source_data="BR2_PACKAGE_BUSYBOX=y\n")
    session.commit()
    assert job.id
    assert job.import_kind == "buildroot"
    assert job.status == "pending"


def test_create_job_invalid_kind(session):
    with pytest.raises(ValueError, match="Invalid import_kind"):
        imp_svc.create_import_job(session, import_kind="windows")


# ---------------------------------------------------------------------------
# list_import_jobs
# ---------------------------------------------------------------------------

def test_list_empty(session):
    assert imp_svc.list_import_jobs(session) == []


def test_list_filter_by_kind(session):
    imp_svc.create_import_job(session, import_kind="buildroot")
    imp_svc.create_import_job(session, import_kind="debian")
    session.commit()
    br_jobs = imp_svc.list_import_jobs(session, import_kind="buildroot")
    assert len(br_jobs) == 1


# ---------------------------------------------------------------------------
# get_import_job
# ---------------------------------------------------------------------------

def test_get_existing(session):
    job = imp_svc.create_import_job(session, import_kind="alpine")
    session.commit()
    fetched = imp_svc.get_import_job(session, job.id)
    assert fetched.id == job.id


def test_get_missing_raises(session):
    with pytest.raises(KeyError):
        imp_svc.get_import_job(session, "nonexistent")


# ---------------------------------------------------------------------------
# run_import — buildroot
# ---------------------------------------------------------------------------

BR2_CONFIG = """\
# Buildroot config
BR2_PACKAGE_BUSYBOX=y
BR2_PACKAGE_BASH=y
BR2_PACKAGE_GZIP=y
# BR2_PACKAGE_COMMENTED is not set
"""

def test_run_import_buildroot(session):
    job = imp_svc.create_import_job(session, import_kind="buildroot", source_data=BR2_CONFIG)
    session.commit()
    report = imp_svc.run_import(session, job.id)
    session.commit()
    assert report.mapped_count == 3
    assert report.report_text
    assert job.status == "done"


def test_run_import_buildroot_no_data(session):
    job = imp_svc.create_import_job(session, import_kind="buildroot", source_data="")
    session.commit()
    report = imp_svc.run_import(session, job.id)
    session.commit()
    assert report.mapped_count == 0


# ---------------------------------------------------------------------------
# run_import — debian
# ---------------------------------------------------------------------------

DEBIAN_PACKAGES = "busybox\nbash\ngzip\n\n# comment\n"

def test_run_import_debian(session):
    job = imp_svc.create_import_job(session, import_kind="debian", source_data=DEBIAN_PACKAGES)
    session.commit()
    report = imp_svc.run_import(session, job.id)
    session.commit()
    assert report.mapped_count >= 2


# ---------------------------------------------------------------------------
# run_import — kconfig
# ---------------------------------------------------------------------------

KCONFIG = """\
CONFIG_BUSYBOX=y
CONFIG_BASH=y
# CONFIG_THING is not set
"""

def test_run_import_kconfig(session):
    job = imp_svc.create_import_job(session, import_kind="kconfig", source_data=KCONFIG)
    session.commit()
    report = imp_svc.run_import(session, job.id)
    session.commit()
    assert report.mapped_count == 2


# ---------------------------------------------------------------------------
# get_import_report
# ---------------------------------------------------------------------------

def test_get_report_after_run(session):
    job = imp_svc.create_import_job(session, import_kind="buildroot", source_data=BR2_CONFIG)
    session.commit()
    imp_svc.run_import(session, job.id)
    session.commit()
    report = imp_svc.get_import_report(session, job.id)
    assert report is not None
    assert report.import_job_id == job.id


def test_get_report_none_before_run(session):
    job = imp_svc.create_import_job(session, import_kind="buildroot")
    session.commit()
    report = imp_svc.get_import_report(session, job.id)
    assert report is None
