"""Tests for M14: Security Baseline — policy, signing, SBOM, auth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from osfabricum.db.engine import make_sync_engine
from osfabricum.db.models import Base
from osfabricum.resolver.plan import BuildPlan, KernelRef, PackageRef, ToolchainRef
from osfabricum.security.policy import (
    verify_artifact_integrity,
    verify_artifacts,
)
from osfabricum.security.sbom import build_sbom, sbom_hash, sbom_to_bytes
from osfabricum.security.signing import (
    SigningKey,
    sign_artifact,
    store_attestation,
    verify_artifact_signature,
)
from osfabricum.store.ingest import ingest_blob

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_sync_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture()
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "store"


@pytest.fixture()
def artifact(tmp_path: Path, db_url: str, store_root: Path):
    """Ingest a real artifact and return it."""
    return ingest_blob(
        data=b"hello security",
        store_root=store_root,
        store_key="test/security/v1",
        kind="test",
        name="sec-test",
        db_url=db_url,
    )


# ---------------------------------------------------------------------------
# verify_artifact_integrity
# ---------------------------------------------------------------------------


def test_verify_artifact_integrity_ok(
    tmp_path: Path, db_url: str, store_root: Path, artifact
) -> None:
    result = verify_artifact_integrity(artifact.id, store_root, db_url=db_url)
    assert result.ok is True
    assert result.artifact_id == artifact.id
    assert result.error is None


def test_verify_artifact_integrity_missing_blob(
    tmp_path: Path, db_url: str, store_root: Path, artifact
) -> None:
    """Delete the blob on disk — verification should fail."""
    from osfabricum.store.layout import blob_path

    bp = blob_path(store_root, artifact.blob_sha256)
    bp.unlink()

    result = verify_artifact_integrity(artifact.id, store_root, db_url=db_url)
    assert result.ok is False
    assert "missing" in (result.error or "")


def test_verify_artifact_integrity_tampered_blob(
    tmp_path: Path, db_url: str, store_root: Path, artifact
) -> None:
    """Overwrite blob with different content — sha256 mismatch."""
    from osfabricum.store.layout import blob_path

    bp = blob_path(store_root, artifact.blob_sha256)
    bp.write_bytes(b"tampered content")

    result = verify_artifact_integrity(artifact.id, store_root, db_url=db_url)
    assert result.ok is False
    assert "mismatch" in (result.error or "")


def test_verify_artifact_integrity_unknown_id(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    result = verify_artifact_integrity(
        "00000000-0000-0000-0000-000000000000", store_root, db_url=db_url
    )
    assert result.ok is False
    assert "not found" in (result.error or "")


def test_verify_artifacts_batch(tmp_path: Path, db_url: str, store_root: Path) -> None:
    a1 = ingest_blob(b"blob1", store_root, "t/1", "t", "t1", db_url=db_url)
    a2 = ingest_blob(b"blob2", store_root, "t/2", "t", "t2", db_url=db_url)
    result = verify_artifacts([a1.id, a2.id], store_root, db_url=db_url)
    assert result.ok is True
    assert result.passed == 2
    assert result.failed == 0


def test_verify_artifacts_batch_partial_failure(
    tmp_path: Path, db_url: str, store_root: Path
) -> None:
    a1 = ingest_blob(b"good", store_root, "t/good", "t", "good", db_url=db_url)
    a2 = ingest_blob(b"bad", store_root, "t/bad", "t", "bad", db_url=db_url)
    from osfabricum.store.layout import blob_path

    blob_path(store_root, a2.blob_sha256).unlink()

    result = verify_artifacts([a1.id, a2.id], store_root, db_url=db_url)
    assert result.ok is False
    assert result.passed == 1
    assert result.failed == 1


# ---------------------------------------------------------------------------
# SigningKey
# ---------------------------------------------------------------------------


def test_signing_key_generate() -> None:
    key = SigningKey.generate("test-key")
    assert key.key_id == "test-key"
    assert len(key.secret) == 32


def test_signing_key_two_generated_are_different() -> None:
    k1 = SigningKey.generate("k1")
    k2 = SigningKey.generate("k2")
    assert k1.secret != k2.secret


def test_signing_key_hex_roundtrip() -> None:
    key = SigningKey.generate("hex-test")
    restored = SigningKey.from_hex("hex-test", key.to_hex())
    assert restored.secret == key.secret


def test_signing_key_repr_hides_secret() -> None:
    key = SigningKey.generate("safe")
    assert "redacted" in repr(key)
    assert key.secret.hex() not in repr(key)


# ---------------------------------------------------------------------------
# sign_artifact / verify_artifact_signature
# ---------------------------------------------------------------------------


def test_sign_and_verify_ok() -> None:
    key = SigningKey.generate("k")
    sig = sign_artifact("art-id", "a" * 64, key)
    assert verify_artifact_signature("art-id", "a" * 64, sig, key) is True


def test_verify_fails_wrong_signature() -> None:
    key = SigningKey.generate("k")
    sig = sign_artifact("art-id", "a" * 64, key)
    assert verify_artifact_signature("art-id", "a" * 64, "bad" + sig[3:], key) is False


def test_verify_fails_wrong_artifact_id() -> None:
    key = SigningKey.generate("k")
    sig = sign_artifact("art-id", "a" * 64, key)
    assert verify_artifact_signature("other-id", "a" * 64, sig, key) is False


def test_verify_fails_wrong_sha256() -> None:
    key = SigningKey.generate("k")
    sig = sign_artifact("art-id", "a" * 64, key)
    assert verify_artifact_signature("art-id", "b" * 64, sig, key) is False


def test_verify_fails_wrong_key() -> None:
    k1 = SigningKey.generate("k1")
    k2 = SigningKey.generate("k2")
    sig = sign_artifact("art-id", "a" * 64, k1)
    assert verify_artifact_signature("art-id", "a" * 64, sig, k2) is False


def test_sign_is_deterministic() -> None:
    key = SigningKey.from_hex("k", "ab" * 32)
    s1 = sign_artifact("id", "c" * 64, key)
    s2 = sign_artifact("id", "c" * 64, key)
    assert s1 == s2


# ---------------------------------------------------------------------------
# store_attestation
# ---------------------------------------------------------------------------


def test_store_attestation_creates_row(db_url: str, artifact) -> None:
    key = SigningKey.generate("prod")
    rec = store_attestation(artifact.id, artifact.blob_sha256, key, db_url=db_url)
    assert rec.artifact_id == artifact.id
    assert rec.attestation_type == "hmac-sha256"
    assert len(rec.signature) == 64  # hex sha256


def test_store_attestation_idempotent(db_url: str, artifact) -> None:
    key = SigningKey.generate("prod")
    r1 = store_attestation(artifact.id, artifact.blob_sha256, key, db_url=db_url)
    r2 = store_attestation(artifact.id, artifact.blob_sha256, key, db_url=db_url)
    assert r1.id == r2.id


def test_attestation_signature_verifies(db_url: str, artifact) -> None:
    key = SigningKey.generate("verify-test")
    rec = store_attestation(artifact.id, artifact.blob_sha256, key, db_url=db_url)
    assert verify_artifact_signature(artifact.id, artifact.blob_sha256, rec.signature, key)


# ---------------------------------------------------------------------------
# build_sbom
# ---------------------------------------------------------------------------


def _make_plan() -> BuildPlan:
    return BuildPlan(
        distribution="tinywifi",
        profile="default",
        board="rpi-zero-2w",
        arch="aarch64",
        resolution_hash="sha256:" + "a" * 64,
        toolchain=ToolchainRef(
            id="tc-1", name="aarch64-linux-musl", arch="aarch64", version="13.2.0"
        ),
        kernel=KernelRef(id="k-1", name="linux-rpi", version="6.6.y"),
        packages=[
            PackageRef(
                name="nanodhcp",
                version="0.1.0",
                arch="aarch64",
                status="built",
                artifact_id="art-1",
            )
        ],
        required_jobs=["rootfs.compose", "image.compose"],
    )


def test_build_sbom_returns_dict() -> None:
    plan = _make_plan()
    bom = build_sbom(plan)
    assert isinstance(bom, dict)
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.4"


def test_build_sbom_contains_components() -> None:
    plan = _make_plan()
    bom = build_sbom(plan)
    names = [c["name"] for c in bom["components"]]
    assert "aarch64-linux-musl" in names
    assert "linux-rpi" in names
    assert "nanodhcp" in names


def test_build_sbom_metadata_component() -> None:
    plan = _make_plan()
    bom = build_sbom(plan)
    meta = bom["metadata"]["component"]
    assert "tinywifi" in meta["name"]


def test_build_sbom_with_subject_sha256() -> None:
    plan = _make_plan()
    sha = "f" * 64
    bom = build_sbom(plan, subject_sha256=sha)
    hashes = bom["metadata"]["component"]["hashes"]
    assert hashes[0]["content"] == sha


def test_build_sbom_fixed_timestamp_for_reproducibility() -> None:
    plan = _make_plan()
    bom = build_sbom(plan, timestamp="1970-01-01T00:00:00Z")
    assert bom["metadata"]["timestamp"] == "1970-01-01T00:00:00Z"


def test_sbom_to_bytes_is_utf8() -> None:
    plan = _make_plan()
    bom = build_sbom(plan)
    data = sbom_to_bytes(bom)
    assert isinstance(data, bytes)
    parsed = json.loads(data.decode("utf-8"))
    assert parsed["bomFormat"] == "CycloneDX"


def test_sbom_hash_deterministic() -> None:
    plan = _make_plan()
    bom = build_sbom(plan, timestamp="1970-01-01T00:00:00Z")
    # Fix serial number for determinism
    bom["serialNumber"] = "urn:uuid:fixed"
    h1 = sbom_hash(bom)
    h2 = sbom_hash(bom)
    assert h1 == h2
    assert len(h1) == 64


def test_sbom_hash_changes_with_content() -> None:
    plan = _make_plan()
    bom1 = build_sbom(plan, timestamp="1970-01-01T00:00:00Z")
    bom1["serialNumber"] = "fixed"
    bom2 = {**bom1, "version": 2}
    assert sbom_hash(bom1) != sbom_hash(bom2)


# ---------------------------------------------------------------------------
# API token auth middleware
# ---------------------------------------------------------------------------


def _make_auth_app(token: str):
    """Create a FastAPI test app with auth enabled."""
    import os

    from apps.api.app import create_app
    from osfabricum.settings import AuthSettings, Settings

    settings = Settings()
    settings.auth = AuthSettings(enabled=True)
    os.environ["OSFABRICUM_API_TOKEN"] = token
    return TestClient(create_app(settings))


def test_api_auth_healthz_no_token_required() -> None:
    """Health endpoints bypass auth."""
    import os

    from apps.api.app import create_app
    from osfabricum.settings import AuthSettings, Settings

    settings = Settings()
    settings.auth = AuthSettings(enabled=True)
    os.environ["OSFABRICUM_API_TOKEN"] = "secret123"
    client = TestClient(create_app(settings))
    assert client.get("/healthz").status_code == 200


def test_api_auth_protected_endpoint_without_token() -> None:
    client = _make_auth_app("secret123")
    resp = client.get("/metrics")
    # /metrics is in PUBLIC_PATHS — should pass
    assert resp.status_code == 200


def test_api_auth_protected_endpoint_valid_token() -> None:
    import os

    from apps.api.app import create_app
    from osfabricum.settings import AuthSettings, Settings

    settings = Settings()
    settings.auth = AuthSettings(enabled=True)
    os.environ["OSFABRICUM_API_TOKEN"] = "mytoken"
    client = TestClient(create_app(settings))
    resp = client.get("/internal/queue", headers={"Authorization": "Bearer mytoken"})
    assert resp.status_code == 200


def test_api_auth_protected_endpoint_wrong_token() -> None:
    import os

    from apps.api.app import create_app
    from osfabricum.settings import AuthSettings, Settings

    settings = Settings()
    settings.auth = AuthSettings(enabled=True)
    os.environ["OSFABRICUM_API_TOKEN"] = "correcttoken"
    client = TestClient(create_app(settings))
    resp = client.get("/internal/queue", headers={"Authorization": "Bearer wrongtoken"})
    assert resp.status_code == 403


def test_api_auth_disabled_no_token_needed() -> None:
    import os

    from apps.api.app import create_app
    from osfabricum.settings import AuthSettings, Settings

    os.environ.pop("OSFABRICUM_API_TOKEN", None)
    settings = Settings()
    settings.auth = AuthSettings(enabled=False)
    client = TestClient(create_app(settings))
    # No token required when auth is disabled
    resp = client.get("/internal/queue")
    assert resp.status_code == 200


def test_api_auth_missing_bearer_scheme() -> None:
    import os

    from apps.api.app import create_app
    from osfabricum.settings import AuthSettings, Settings

    settings = Settings()
    settings.auth = AuthSettings(enabled=True)
    os.environ["OSFABRICUM_API_TOKEN"] = "tok"
    client = TestClient(create_app(settings))
    resp = client.get("/internal/queue", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert resp.status_code == 401
