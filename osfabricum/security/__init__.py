"""Security baseline (M14) — integrity verification, signing, SBOM."""

from osfabricum.security.policy import (
    BatchVerificationResult,
    VerificationResult,
    verify_artifact_integrity,
    verify_artifacts,
)
from osfabricum.security.sbom import build_sbom, sbom_hash, sbom_to_bytes
from osfabricum.security.signing import (
    AttestationRecord,
    SigningKey,
    list_attestations,
    sign_artifact,
    store_attestation,
    verify_artifact_signature,
)

__all__ = [
    # policy
    "BatchVerificationResult",
    "VerificationResult",
    "verify_artifact_integrity",
    "verify_artifacts",
    # signing
    "AttestationRecord",
    "SigningKey",
    "list_attestations",
    "sign_artifact",
    "store_attestation",
    "verify_artifact_signature",
    # sbom
    "build_sbom",
    "sbom_hash",
    "sbom_to_bytes",
]
