"""The Alembic migration chain runs cleanly and matches the ORM models (G-23).

Historically the chain was broken from scratch: ``0001`` uses
``metadata.create_all`` (building the *current* model schema), so the
incremental ``add_column`` migrations collided ("duplicate column"). M25 guards
every incremental migration (matching the convention established in ``0002``)
so ``alembic upgrade head`` runs on a fresh database, creates every model table
and column, and seeds the fixed enumerations. This test is the permanent guard.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from osfabricum.db.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cfg(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def test_upgrade_head_matches_models_and_seeds(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db_url = f"sqlite:///{tmp_path / 'mig.db'}"
    monkeypatch.setenv("OSFABRICUM_DB_URL", db_url)

    command.upgrade(_cfg(db_url), "head")

    engine = sa.create_engine(db_url)
    try:
        insp = sa.inspect(engine)
        db_tables = set(insp.get_table_names())

        # Every model table exists in the migrated database.
        missing_tables = set(Base.metadata.tables) - db_tables
        assert not missing_tables, f"migrated DB missing model tables: {missing_tables}"

        # Every model column exists in the migrated database (drift guard).
        for table_name, table in Base.metadata.tables.items():
            db_cols = {c["name"] for c in insp.get_columns(table_name)}
            model_cols = {c.name for c in table.columns}
            assert not (model_cols - db_cols), (
                f"{table_name} missing columns in migrated DB: {model_cols - db_cols}"
            )

        # The fixed enumerations were seeded by migration 0006.
        with engine.connect() as conn:
            classes = conn.execute(sa.text("SELECT count(*) FROM distribution_classes")).scalar()
            schemes = conn.execute(sa.text("SELECT count(*) FROM boot_schemes")).scalar()
        assert classes == 11
        assert schemes == 8
    finally:
        engine.dispose()


def test_upgrade_then_downgrade_roundtrip(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db_url = f"sqlite:///{tmp_path / 'rt.db'}"
    monkeypatch.setenv("OSFABRICUM_DB_URL", db_url)
    cfg = _cfg(db_url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")  # 0006 -> 0005

    engine = sa.create_engine(db_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert "distribution_classes" not in tables
        assert "package_sets" not in tables
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")  # back up cleanly
    engine = sa.create_engine(db_url)
    try:
        assert "distribution_classes" in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
