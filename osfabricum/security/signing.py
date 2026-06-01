"""Artifact signing and attestation (M14).

Uses HMAC-SHA256 (stdlib ``hmac`` + ``hashlib``) as the signing primitive —
no external crypto dependency.  The scheme is:

    signature = HMAC-SHA256(key=secret, msg=f"{key_id}:{artifact_id}:{blob_sha256}")

``SigningKey``
    A named key with a 32-byte secret.  Store the secret securely
    (environment variable, Vault, etc.) — never commit it.

``sign_artifact``
    Produce a lowercase hex HMAC-SHA256 signature for an artifact.

``verify_artifact_signature``
    Constant-time comparison of an expected vs. provided signature.

``store_attestation``
    Upsert an :class:`~osfabricum.db.models.ArtifactAttestation` row.

``list_attestations``
    Return all attestations for an artifact ID.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from sqlalchemy import select

from osfabricum.db.models import ArtifactAttestation
from osfabricum.db.session import sync_session

_HMAC_MSG_SEP = ":"
_ATTESTATION_TYPE = "hmac-sha256"


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


@dataclass
class SigningKey:
    """A named HMAC-SHA256 signing key.

    Attributes
    ----------
    key_id:
        Human-readable identifier (e.g. ``"prod-sign-v1"``).
    secret:
        32-byte raw secret.  **Never log or commit this value.**
    """

    key_id: str
    secret: bytes

    def __repr__(self) -> str:
        return f"SigningKey(key_id={self.key_id!r}, secret=<redacted>)"

    @classmethod
    def generate(cls, key_id: str) -> SigningKey:
        """Generate a new random 32-byte key."""
        return cls(key_id=key_id, secret=secrets.token_bytes(32))

    @classmethod
    def from_hex(cls, key_id: str, hex_secret: str) -> SigningKey:
        """Load a key from a lowercase hex string (64 chars = 32 bytes)."""
        return cls(key_id=key_id, secret=bytes.fromhex(hex_secret))

    def to_hex(self) -> str:
        """Return the secret as a lowercase hex string (for storage)."""
        return self.secret.hex()


# ---------------------------------------------------------------------------
# Sign / verify
# ---------------------------------------------------------------------------


def _hmac_message(key_id: str, artifact_id: str, blob_sha256: str) -> bytes:
    parts = [key_id, artifact_id, blob_sha256]
    return _HMAC_MSG_SEP.join(parts).encode("utf-8")


def sign_artifact(
    artifact_id: str,
    blob_sha256: str,
    key: SigningKey,
) -> str:
    """Return a lowercase hex HMAC-SHA256 signature.

    Parameters
    ----------
    artifact_id:
        UUID of the artifact.
    blob_sha256:
        ``Artifact.blob_sha256`` value.
    key:
        The :class:`SigningKey` to sign with.

    Returns
    -------
    str
        64-character lowercase hex digest.
    """
    msg = _hmac_message(key.key_id, artifact_id, blob_sha256)
    return hmac.new(key.secret, msg, hashlib.sha256).hexdigest()


def verify_artifact_signature(
    artifact_id: str,
    blob_sha256: str,
    signature: str,
    key: SigningKey,
) -> bool:
    """Constant-time comparison of *signature* with the expected value.

    Returns
    -------
    bool
        ``True`` iff the signature is valid for the given key and artifact.
    """
    expected = sign_artifact(artifact_id, blob_sha256, key)
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Attestation persistence
# ---------------------------------------------------------------------------


@dataclass
class AttestationRecord:
    """Minimal view of an :class:`~osfabricum.db.models.ArtifactAttestation` row."""

    id: str
    artifact_id: str
    attestation_type: str
    key_id: str
    signature: str


def store_attestation(
    artifact_id: str,
    blob_sha256: str,
    key: SigningKey,
    *,
    db_url: str | None = None,
) -> AttestationRecord:
    """Sign *artifact_id* and persist an ``ArtifactAttestation`` row.

    If an attestation of type ``"hmac-sha256"`` already exists for
    *artifact_id* it is **not** duplicated; the existing row is returned.

    Parameters
    ----------
    artifact_id:
        UUID of the artifact to sign.
    blob_sha256:
        ``Artifact.blob_sha256`` — included in the signed message.
    key:
        The :class:`SigningKey` to sign with.
    db_url:
        SQLAlchemy database URL.

    Returns
    -------
    AttestationRecord
        The (possibly newly created) attestation record.
    """
    signature = sign_artifact(artifact_id, blob_sha256, key)

    with sync_session(db_url) as session:
        # Dedup: one hmac-sha256 attestation per artifact
        existing: ArtifactAttestation | None = session.scalar(
            select(ArtifactAttestation).where(
                ArtifactAttestation.artifact_id == artifact_id,
                ArtifactAttestation.attestation_type == _ATTESTATION_TYPE,
            )
        )
        if existing is not None:
            return AttestationRecord(
                id=existing.id,
                artifact_id=existing.artifact_id,
                attestation_type=existing.attestation_type,
                key_id=key.key_id,
                signature=signature,
            )

        row = ArtifactAttestation(
            artifact_id=artifact_id,
            attestation_type=_ATTESTATION_TYPE,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

    return AttestationRecord(
        id=row.id,
        artifact_id=artifact_id,
        attestation_type=_ATTESTATION_TYPE,
        key_id=key.key_id,
        signature=signature,
    )


def list_attestations(
    artifact_id: str,
    *,
    db_url: str | None = None,
) -> list[ArtifactAttestation]:
    """Return all ``ArtifactAttestation`` rows for *artifact_id*."""
    with sync_session(db_url) as session:
        return list(
            session.scalars(
                select(ArtifactAttestation).where(
                    ArtifactAttestation.artifact_id == artifact_id
                )
            ).all()
        )
