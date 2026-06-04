"""Tests for M7: Source Fetcher (fetch, verify, cache, offline, CLI, worker)."""

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
from osfabricum.db.models import Artifact, Base, Source
from osfabricum.db.session import sync_session
from osfabricum.fetcher.fetch import fetch_source
from osfabricum.fetcher.handler import make_source_fetch_handler
from osfabricum.queue.backend import JobBackend
from osfabricum.queue.worker import WorkerLoop
from osfabricum.store.layout import compute_sha256

runner = CliRunner()

_FAKE_TARBALL = b"fake-tarball-content-abc123"
_FAKE_SHA256 = compute_sha256(_FAKE_TARBALL)


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


def _add_source(
    db_url: str,
    *,
    uri: str,
    source_type: str = "http",
    ref: str | None = None,
    expected_hash: str | None = None,
    name: str | None = None,
    tarball_url: str | None = None,
) -> str:
    """Insert a Source row; return its id."""
    meta: dict[str, object] = {}
    if name:
        meta["name"] = name
    if tarball_url:
        meta["tarball_url"] = tarball_url
    with sync_session(db_url) as session:
        src = Source(
            uri=uri,
            source_type=source_type,
            ref=ref,
            expected_hash=expected_hash,
            metadata_json=meta or None,
        )
        session.add(src)
        session.commit()
        session.refresh(src)
        return src.id


def _mock_urlopen(data: bytes = _FAKE_TARBALL) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = data
    return mock_resp


# ---------------------------------------------------------------------------
# fetch_source — HTTP
# ---------------------------------------------------------------------------


def test_fetch_http_downloads_and_stores(db_url: str, store_root: Path) -> None:
    _add_source(db_url, uri="https://example.com/pkg-1.0.tar.gz", name="pkg-1.0")

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        artifact_id = fetch_source("pkg-1.0", store_root, db_url)

    assert artifact_id
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
    assert art is not None
    assert art.kind == "source"
    assert art.name == "pkg-1.0"
    assert art.size_bytes == len(_FAKE_TARBALL)
    assert art.blob_sha256 == _FAKE_SHA256


def test_fetch_http_by_uri(db_url: str, store_root: Path) -> None:
    uri = "https://example.com/archive.tar.bz2"
    _add_source(db_url, uri=uri)

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        artifact_id = fetch_source(uri, store_root, db_url)

    assert artifact_id


def test_fetch_http_by_id(db_url: str, store_root: Path) -> None:
    src_id = _add_source(db_url, uri="https://example.com/foo.tar.gz")

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        artifact_id = fetch_source(src_id, store_root, db_url)

    assert artifact_id


def test_fetch_http_verifies_sha256(db_url: str, store_root: Path) -> None:
    _add_source(
        db_url,
        uri="https://example.com/verified.tar.gz",
        expected_hash=_FAKE_SHA256,
    )
    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        artifact_id = fetch_source("https://example.com/verified.tar.gz", store_root, db_url)
    assert artifact_id


def test_fetch_http_sha256_mismatch_rejected(db_url: str, store_root: Path) -> None:
    _add_source(
        db_url,
        uri="https://example.com/bad.tar.gz",
        expected_hash="0" * 64,
    )
    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        with pytest.raises(ValueError, match="sha256 mismatch"):
            fetch_source("https://example.com/bad.tar.gz", store_root, db_url)

    # store must not contain the bad blob
    with sync_session(db_url) as session:
        count = len(session.scalars(select(Artifact).where(Artifact.kind == "source")).all())
    assert count == 0


def test_fetch_sha256_prefix_normalised(db_url: str, store_root: Path) -> None:
    """expected_hash stored with 'sha256:' prefix is accepted."""
    _add_source(
        db_url,
        uri="https://example.com/ok.tar.gz",
        expected_hash=f"sha256:{_FAKE_SHA256}",
    )
    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        art_id = fetch_source("https://example.com/ok.tar.gz", store_root, db_url)
    assert art_id


# ---------------------------------------------------------------------------
# fetch_source — git (tarball_url fast path)
# ---------------------------------------------------------------------------


def test_fetch_git_tarball_url(db_url: str, store_root: Path) -> None:
    _add_source(
        db_url,
        uri="https://github.com/example/repo",
        source_type="git",
        ref="abc1234",
        name="myrepo",
        tarball_url="https://github.com/example/repo/archive/abc1234.tar.gz",
    )
    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        artifact_id = fetch_source("myrepo", store_root, db_url)

    assert artifact_id
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
    assert art is not None
    assert art.version == "abc1234"
    assert art.store_key.endswith("abc1234.tar.gz")


# ---------------------------------------------------------------------------
# fetch_source — git (subprocess fallback)
# ---------------------------------------------------------------------------


def test_fetch_git_subprocess_fallback(db_url: str, store_root: Path) -> None:
    _add_source(
        db_url,
        uri="https://git.example.com/repo.git",
        source_type="git",
        ref="v1.0",
        name="repo-v1",
        # no tarball_url → subprocess path
    )

    def _fake_clone(
        cmd: list[str],
        *,
        check: bool,
        capture_output: bool,
    ) -> MagicMock:
        clone_dir = cmd[-1]
        Path(clone_dir).mkdir(parents=True, exist_ok=True)
        (Path(clone_dir) / "main.c").write_bytes(b"int main() {}")
        return MagicMock(returncode=0)

    with patch("osfabricum.fetcher.git.subprocess.run", side_effect=_fake_clone):
        artifact_id = fetch_source("repo-v1", store_root, db_url)

    assert artifact_id
    with sync_session(db_url) as session:
        art = session.scalar(select(Artifact).where(Artifact.id == artifact_id))
    assert art is not None
    assert art.version == "v1.0"


# ---------------------------------------------------------------------------
# Cache deduplication
# ---------------------------------------------------------------------------


def test_fetch_cache_hit_no_redownload(db_url: str, store_root: Path) -> None:
    """Second call returns same artifact without hitting the network."""
    _add_source(db_url, uri="https://example.com/cacheme.tar.gz", name="cache-me")

    call_count = 0

    def _counting_open(url: str) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return _mock_urlopen()

    with patch("urllib.request.urlopen", side_effect=_counting_open):
        id1 = fetch_source("cache-me", store_root, db_url)

    with patch("urllib.request.urlopen", side_effect=_counting_open):
        id2 = fetch_source("cache-me", store_root, db_url)

    assert id1 == id2
    assert call_count == 1  # network called only once


# ---------------------------------------------------------------------------
# Offline mode
# ---------------------------------------------------------------------------


def test_fetch_offline_hit(db_url: str, store_root: Path) -> None:
    """Offline mode returns cached artifact without network access."""
    _add_source(db_url, uri="https://example.com/offline.tar.gz", name="offline-src")

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        art_id = fetch_source("offline-src", store_root, db_url)

    offline_id = fetch_source("offline-src", store_root, db_url, offline=True)
    assert offline_id == art_id


def test_fetch_offline_miss_raises(db_url: str, store_root: Path) -> None:
    """Offline mode raises RuntimeError when source is not in cache."""
    _add_source(db_url, uri="https://example.com/notcached.tar.gz", name="notcached")

    with pytest.raises(RuntimeError, match="offline mode"):
        fetch_source("notcached", store_root, db_url, offline=True)


def test_fetch_not_found_raises(db_url: str, store_root: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        fetch_source("nonexistent-source", store_root, db_url)


def test_fetch_unsupported_type_raises(db_url: str, store_root: Path) -> None:
    _add_source(db_url, uri="ftp://example.com/old.tar.gz", source_type="ftp")
    with pytest.raises(ValueError, match="unsupported source_type"):
        fetch_source("ftp://example.com/old.tar.gz", store_root, db_url)


# ---------------------------------------------------------------------------
# catalog import — SourceList
# ---------------------------------------------------------------------------


def test_import_sources(db_url: str, tmp_path: Path) -> None:
    src_file = tmp_path / "sources.yaml"
    src_file.write_text(
        textwrap.dedent("""\
            apiVersion: osfabricum/v1
            kind: SourceList
            items:
              - uri: https://example.com/pkg-a-1.0.tar.gz
                source_type: http
                metadata:
                  name: pkg-a-1.0
              - uri: https://github.com/example/repo
                source_type: git
                ref: main
                metadata:
                  name: repo
                  tarball_url: "https://github.com/example/repo/archive/main.tar.gz"
        """)
    )
    result = runner.invoke(app, ["catalog", "import", "--file", str(src_file), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "2" in result.output

    with sync_session(db_url) as session:
        rows = session.scalars(select(Source)).all()
    assert len(rows) == 2


def test_import_sources_idempotent(db_url: str, tmp_path: Path) -> None:
    src_file = tmp_path / "src.yaml"
    src_file.write_text(
        "kind: SourceList\nitems:\n  - uri: https://example.com/foo.tar.gz\n    source_type: http\n"
    )
    runner.invoke(app, ["catalog", "import", "--file", str(src_file), "--db-url", db_url])
    result = runner.invoke(app, ["catalog", "import", "--file", str(src_file), "--db-url", db_url])
    assert result.exit_code == 0
    assert "0" in result.output


# ---------------------------------------------------------------------------
# CLI: source list / show / add / fetch
# ---------------------------------------------------------------------------


def test_cli_source_list_empty(db_url: str) -> None:
    result = runner.invoke(app, ["source", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "Sources" in result.output


def test_cli_source_list_shows_entry(db_url: str) -> None:
    _add_source(
        db_url,
        uri="https://example.com/mylib-2.0.tar.gz",
        name="mylib-2.0",
    )
    result = runner.invoke(app, ["source", "list", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "mylib-2.0" in result.output


def test_cli_source_add(db_url: str) -> None:
    result = runner.invoke(
        app,
        [
            "source",
            "add",
            "https://example.com/newpkg-1.0.tar.gz",
            "--type",
            "http",
            "--name",
            "newpkg-1.0",
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "newpkg-1.0" in result.output

    with sync_session(db_url) as session:
        src = session.scalar(
            select(Source).where(Source.uri == "https://example.com/newpkg-1.0.tar.gz")
        )
    assert src is not None
    assert (src.metadata_json or {}).get("name") == "newpkg-1.0"


def test_cli_source_add_idempotent(db_url: str) -> None:
    uri = "https://example.com/dup.tar.gz"
    runner.invoke(app, ["source", "add", uri, "--db-url", db_url])
    result = runner.invoke(app, ["source", "add", uri, "--db-url", db_url])
    assert result.exit_code == 0
    assert "already registered" in result.output


def test_cli_source_show(db_url: str) -> None:
    _add_source(
        db_url,
        uri="https://example.com/showme.tar.gz",
        name="showme",
        expected_hash=_FAKE_SHA256,
    )
    result = runner.invoke(app, ["source", "show", "showme", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "showme" in result.output
    assert _FAKE_SHA256 in result.output


def test_cli_source_show_not_found(db_url: str) -> None:
    result = runner.invoke(app, ["source", "show", "nonexistent", "--db-url", db_url])
    assert result.exit_code != 0


def test_cli_source_fetch(db_url: str, store_root: Path) -> None:
    _add_source(db_url, uri="https://example.com/cli-fetch.tar.gz", name="cli-fetch")

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):
        result = runner.invoke(
            app,
            [
                "source",
                "fetch",
                "cli-fetch",
                "--store",
                str(store_root),
                "--db-url",
                db_url,
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Stored as artifact" in result.output


def test_cli_source_fetch_not_found(db_url: str, store_root: Path) -> None:
    result = runner.invoke(
        app,
        ["source", "fetch", "does-not-exist", "--store", str(store_root), "--db-url", db_url],
    )
    assert result.exit_code != 0


def test_cli_source_fetch_offline_miss(db_url: str, store_root: Path) -> None:
    _add_source(db_url, uri="https://example.com/offline-test.tar.gz", name="offline-test")
    result = runner.invoke(
        app,
        [
            "source",
            "fetch",
            "offline-test",
            "--offline",
            "--store",
            str(store_root),
            "--db-url",
            db_url,
        ],
    )
    assert result.exit_code != 0
    combined = result.output.lower() + (result.stderr or "").lower()
    assert "offline mode" in combined


# ---------------------------------------------------------------------------
# Worker handler
# ---------------------------------------------------------------------------


def test_source_fetch_handler_via_worker_loop(db_url: str, store_root: Path) -> None:
    """End-to-end: enqueue → WorkerLoop processes → artifact created."""
    _add_source(
        db_url,
        uri="https://example.com/worker-test.tar.gz",
        name="worker-test",
    )

    backend = JobBackend(db_url)
    backend.enqueue("source.fetch", payload={"source_id": "worker-test"})

    stop = threading.Event()
    loop = WorkerLoop(
        backend,
        "test-worker",
        ["source.fetch"],
        poll_interval_s=0.05,
    )
    loop.register("source.fetch", make_source_fetch_handler(store_root, db_url))

    with patch("urllib.request.urlopen", return_value=_mock_urlopen()):

        def _run() -> None:
            loop.run(stop)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        import time

        deadline = time.monotonic() + 5.0
        art_id: str | None = None
        while time.monotonic() < deadline:
            if backend.status_counts().get("success", 0) >= 1:
                with sync_session(db_url) as session:
                    art = session.scalar(select(Artifact).where(Artifact.kind == "source"))
                    art_id = art.id if art else None
                break
            time.sleep(0.05)

        stop.set()
        t.join(timeout=3.0)

    assert art_id is not None, "Expected a source artifact in the store"


def test_source_fetch_handler_missing_payload(db_url: str, store_root: Path) -> None:
    backend = JobBackend(db_url)
    backend.enqueue("source.fetch", payload={})  # no source_id

    stop = threading.Event()
    loop = WorkerLoop(backend, "test-worker", ["source.fetch"], poll_interval_s=0.05)
    loop.register("source.fetch", make_source_fetch_handler(store_root, db_url))

    def _run() -> None:
        loop.run(stop)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    import time

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        sc = backend.status_counts()
        if sc.get("failed", 0) + sc.get("queued", 0) >= 1:
            break
        time.sleep(0.05)

    stop.set()
    t.join(timeout=3.0)

    sc = backend.status_counts()
    assert sc.get("failed", 0) + sc.get("queued", 0) >= 1
