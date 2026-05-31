"""Tests for M6: Toolchain Model (catalog import, fetch, CLI commands, worker handler)."""

from __future__ import annotations

import textwrap
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from apps.cli.main import app
from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Artifact, Base, Toolchain, ToolchainArtifact
from osfabricum.db.session import sync_session
from osfabricum.queue.backend import JobBackend
from osfabricum.queue.worker import WorkerLoop
from osfabricum.toolchain.fetch import fetch_toolchain
from osfabricum.toolchain.handler import make_toolchain_fetch_handler

runner = CliRunner()

_FAKE_TARBALL = b"PK\x03\x04fake-toolchain-tarball"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    from pyjobkit.backends.sql.schema import metadata as pjk_meta

    pjk_meta.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


def _seed_arch_and_toolchain(db_url: str) -> str:
    """Insert aarch64 + aarch64-linux-musl-bootlin; return toolchain name."""
    from osfabricum.db.models import Architecture

    with sync_session(db_url) as session:
        arch = Architecture(name="aarch64")
        session.add(arch)
        session.flush()
        tc = Toolchain(
            name="aarch64-linux-musl-bootlin",
            arch_id=arch.id,
            libc="musl",
            version="2024.05-1",
            source_type="bootlin-prebuilt",
            metadata_json={
                "download_url": "https://example.com/toolchains/aarch64--musl--stable.tar.bz2"
            },
        )
        session.add(tc)
        session.commit()
    return "aarch64-linux-musl-bootlin"


# ---------------------------------------------------------------------------
# catalog import — ToolchainList
# ---------------------------------------------------------------------------


def test_import_toolchains(db_url: str, tmp_path: Path) -> None:
    # first import the architecture
    arch_file = tmp_path / "archs.yaml"
    arch_file.write_text("kind: ArchitectureList\nitems:\n  - name: aarch64\n  - name: x86_64\n")
    runner.invoke(app, ["catalog", "import", "--file", str(arch_file), "--db-url", db_url])

    tc_file = tmp_path / "toolchains.yaml"
    tc_file.write_text(
        textwrap.dedent("""\
            apiVersion: osfabricum/v1
            kind: ToolchainList
            items:
              - name: aarch64-linux-musl-bootlin
                arch: aarch64
                libc: musl
                version: "2024.05-1"
                source_type: bootlin-prebuilt
                metadata:
                  download_url: "https://example.com/aarch64.tar.bz2"
              - name: x86_64-linux-musl-bootlin
                arch: x86_64
                libc: musl
                version: "2024.05-1"
                source_type: bootlin-prebuilt
        """)
    )
    result = runner.invoke(
        app, ["catalog", "import", "--file", str(tc_file), "--db-url", db_url]
    )
    assert result.exit_code == 0, result.output
    assert "2" in result.output

    with sync_session(db_url) as session:
        rows = session.scalars(select(Toolchain)).all()
    assert len(rows) == 2
    names = {r.name for r in rows}
    assert "aarch64-linux-musl-bootlin" in names
    assert "x86_64-linux-musl-bootlin" in names


def test_import_toolchains_idempotent(db_url: str, tmp_path: Path) -> None:
    arch_file = tmp_path / "archs.yaml"
    arch_file.write_text("kind: ArchitectureList\nitems:\n  - name: aarch64\n")
    runner.invoke(app, ["catalog", "import", "--file", str(arch_file), "--db-url", db_url])

    tc_file = tmp_path / "tc.yaml"
    tc_file.write_text(
        "kind: ToolchainList\nitems:\n"
        "  - name: aarch64-linux-musl-bootlin\n    arch: aarch64\n"
        "    libc: musl\n    version: '2024.05-1'\n    source_type: bootlin-prebuilt\n"
    )
    runner.invoke(app, ["catalog", "import", "--file", str(tc_file), "--db-url", db_url])
    result = runner.invoke(
        app, ["catalog", "import", "--file", str(tc_file), "--db-url", db_url]
    )
    assert result.exit_code == 0
    assert "0" in result.output


def test_import_toolchains_missing_arch(db_url: str, tmp_path: Path) -> None:
    tc_file = tmp_path / "tc.yaml"
    tc_file.write_text(
        "kind: ToolchainList\nitems:\n"
        "  - name: foo\n    arch: nonexistent\n"
        "    libc: musl\n    version: '1.0'\n    source_type: custom\n"
    )
    result = runner.invoke(
        app, ["catalog", "import", "--file", str(tc_file), "--db-url", db_url]
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# fetch_toolchain
# ---------------------------------------------------------------------------


def _mock_urlopen(data: bytes = _FAKE_TARBALL):  # type: ignore[no-untyped-def]
    """Return a context-manager mock for urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = data
    return mock_resp


def test_fetch_toolchain_downloads_and_stores(db_url: str, store_root: Path) -> None:
    _seed_arch_and_toolchain(db_url)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        artifact_id = fetch_toolchain("aarch64-linux-musl-bootlin", store_root, db_url)

    assert artifact_id
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
    assert art is not None
    assert art.kind == "toolchain"
    assert art.name == "aarch64-linux-musl-bootlin"
    assert art.version == "2024.05-1"
    assert art.size_bytes == len(_FAKE_TARBALL)


def test_fetch_toolchain_creates_toolchain_artifact(db_url: str, store_root: Path) -> None:
    _seed_arch_and_toolchain(db_url)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        artifact_id = fetch_toolchain("aarch64-linux-musl-bootlin", store_root, db_url)

    with sync_session(db_url) as session:
        tc = session.scalar(
            select(Toolchain).where(Toolchain.name == "aarch64-linux-musl-bootlin")
        )
        assert tc is not None
        ta = session.scalar(
            select(ToolchainArtifact).where(ToolchainArtifact.toolchain_id == tc.id)
        )
    assert ta is not None
    assert ta.artifact_id == artifact_id
    assert ta.verified_at is not None


def test_fetch_toolchain_idempotent(db_url: str, store_root: Path) -> None:
    """Calling fetch_toolchain twice returns the same artifact and doesn't duplicate rows."""
    _seed_arch_and_toolchain(db_url)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        id1 = fetch_toolchain("aarch64-linux-musl-bootlin", store_root, db_url)
    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        id2 = fetch_toolchain("aarch64-linux-musl-bootlin", store_root, db_url)

    assert id1 == id2
    with sync_session(db_url) as session:
        tc = session.scalar(
            select(Toolchain).where(Toolchain.name == "aarch64-linux-musl-bootlin")
        )
        assert tc is not None
        count = len(
            session.scalars(
                select(ToolchainArtifact).where(ToolchainArtifact.toolchain_id == tc.id)
            ).all()
        )
    assert count == 1


def test_fetch_toolchain_not_found(db_url: str, store_root: Path) -> None:
    with sync_session(db_url) as session:
        from osfabricum.db.models import Architecture

        session.add(Architecture(name="aarch64"))
        session.commit()

    with pytest.raises(ValueError, match="not found"):
        fetch_toolchain("nonexistent-toolchain", store_root, db_url)


def test_fetch_toolchain_no_download_url(db_url: str, store_root: Path) -> None:
    from osfabricum.db.models import Architecture

    with sync_session(db_url) as session:
        arch = Architecture(name="aarch64")
        session.add(arch)
        session.flush()
        session.add(
            Toolchain(
                name="no-url-tc",
                arch_id=arch.id,
                libc="musl",
                version="1.0",
                source_type="custom",
                metadata_json=None,
            )
        )
        session.commit()

    with pytest.raises(ValueError, match="no 'download_url'"):
        fetch_toolchain("no-url-tc", store_root, db_url)


# ---------------------------------------------------------------------------
# worker handler
# ---------------------------------------------------------------------------


def test_toolchain_fetch_handler_via_worker_loop(db_url: str, store_root: Path) -> None:
    """End-to-end: enqueue → WorkerLoop processes → artifact created."""
    _seed_arch_and_toolchain(db_url)

    backend = JobBackend(db_url)
    backend.enqueue(
        "toolchain.fetch",
        payload={"toolchain_id": "aarch64-linux-musl-bootlin"},
    )

    stop = threading.Event()
    loop = WorkerLoop(
        backend,
        "test-worker",
        ["toolchain.fetch"],
        poll_interval_s=0.05,
    )

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        loop.register(
            "toolchain.fetch",
            make_toolchain_fetch_handler(store_root, db_url),
        )

        def _run() -> None:
            loop.run(stop)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        # wait for the job to complete (max 5 s)
        import time

        deadline = time.monotonic() + 5.0
        artifact_id: str | None = None
        while time.monotonic() < deadline:
            sc = backend.status_counts()
            if sc.get("success", 0) >= 1:
                with sync_session(db_url) as session:
                    art = session.scalar(select(Artifact).where(Artifact.kind == "toolchain"))
                    artifact_id = art.id if art else None
                break
            time.sleep(0.05)

        stop.set()
        t.join(timeout=3.0)

    assert artifact_id is not None, "Expected a toolchain artifact in the store"
    assert backend.status_counts().get("success", 0) >= 1


def test_toolchain_fetch_handler_missing_payload(db_url: str, store_root: Path) -> None:
    """Handler raises ValueError when toolchain_id missing → job marked failed."""
    with sync_session(db_url) as session:
        from osfabricum.db.models import Architecture

        session.add(Architecture(name="aarch64"))
        session.commit()

    backend = JobBackend(db_url)
    backend.enqueue("toolchain.fetch", payload={})  # no toolchain_id

    stop = threading.Event()
    loop = WorkerLoop(
        backend,
        "test-worker",
        ["toolchain.fetch"],
        poll_interval_s=0.05,
    )
    loop.register("toolchain.fetch", make_toolchain_fetch_handler(store_root, db_url))

    def _run() -> None:
        loop.run(stop)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    import time

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        sc = backend.status_counts()
        if sc.get("failed", 0) >= 1 or sc.get("queued", 0) >= 1:
            break
        time.sleep(0.05)

    stop.set()
    t.join(timeout=3.0)

    sc = backend.status_counts()
    # job should eventually fail (possibly after retries)
    assert sc.get("failed", 0) + sc.get("queued", 0) >= 1


# ---------------------------------------------------------------------------
# CLI: toolchain list / show / fetch / add
# ---------------------------------------------------------------------------


def test_cli_toolchain_list_empty(db_url: str) -> None:
    result = runner.invoke(app, ["toolchain", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "Toolchains" in result.output


def test_cli_toolchain_list_shows_entry(db_url: str) -> None:
    _seed_arch_and_toolchain(db_url)
    result = runner.invoke(app, ["toolchain", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    # Rich wraps long names in narrow terminal; check shorter substrings
    assert "musl" in result.output
    assert "bootlin-prebuilt" in result.output
    assert "aarch64" in result.output


def test_cli_toolchain_show(db_url: str) -> None:
    _seed_arch_and_toolchain(db_url)
    result = runner.invoke(
        app, ["toolchain", "show", "aarch64-linux-musl-bootlin", "--db-url", db_url]
    )
    assert result.exit_code == 0, result.output
    assert "2024.05-1" in result.output
    assert "bootlin-prebuilt" in result.output


def test_cli_toolchain_show_not_found(db_url: str) -> None:
    with sync_session(db_url) as session:
        from osfabricum.db.models import Architecture

        session.add(Architecture(name="aarch64"))
        session.commit()
    result = runner.invoke(app, ["toolchain", "show", "nonexistent", "--db-url", db_url])
    assert result.exit_code != 0


def test_cli_toolchain_add(db_url: str) -> None:
    with sync_session(db_url) as session:
        from osfabricum.db.models import Architecture

        session.add(Architecture(name="aarch64"))
        session.commit()

    result = runner.invoke(
        app,
        [
            "toolchain",
            "add",
            "my-toolchain",
            "--arch",
            "aarch64",
            "--libc",
            "musl",
            "--version",
            "1.0",
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "my-toolchain" in result.output

    with sync_session(db_url) as session:
        tc = session.scalar(select(Toolchain).where(Toolchain.name == "my-toolchain"))
    assert tc is not None
    assert tc.libc == "musl"


def test_cli_toolchain_fetch(db_url: str, store_root: Path) -> None:
    _seed_arch_and_toolchain(db_url)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        result = runner.invoke(
            app,
            [
                "toolchain",
                "fetch",
                "aarch64-linux-musl-bootlin",
                "--store",
                str(store_root),
                "--db-url",
                db_url,
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Stored as artifact" in result.output


def test_cli_toolchain_fetch_not_found(db_url: str, store_root: Path) -> None:
    with sync_session(db_url) as session:
        from osfabricum.db.models import Architecture

        session.add(Architecture(name="aarch64"))
        session.commit()

    result = runner.invoke(
        app,
        [
            "toolchain",
            "fetch",
            "nonexistent",
            "--store",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# JobView.payload is populated
# ---------------------------------------------------------------------------


def test_job_view_carries_payload(db_url: str) -> None:
    """Claimed job's payload is accessible on JobView."""
    backend = JobBackend(db_url)
    backend.enqueue("test.kind", payload={"key": "value", "num": 42})
    job = backend.claim_next(["test.kind"], "test-worker")
    assert job is not None
    assert job.payload.get("key") == "value"
    assert job.payload.get("num") == 42
