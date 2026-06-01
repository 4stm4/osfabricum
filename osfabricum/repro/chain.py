"""Reproducibility hash chain (M13).

Every artifact that OSFabricum produces carries a traceable lineage:

    source_hash  ──┐
    config_hash  ──┼──► input_hash ──► expected_output_sha256
    env_hash     ──┘

The same ``input_hash`` from two independent builds implies identical
inputs and environment — if outputs differ, the build is not reproducible.

``InputManifest``
    All inputs to a single build step.

``compute_input_hash``
    Deterministic SHA-256 of an ``InputManifest``.

``ReproRecord``
    Full traceability record stored alongside an artifact.

``verify_repro``
    Assert that a stored ``ReproRecord`` is consistent with a new build's
    output hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class InputManifest:
    """All inputs to one build step.

    Attributes
    ----------
    step_kind:
        Job kind string (e.g. ``"kernel.build"``, ``"package.build"``).
    source_hash:
        SHA-256 hex of the source archive / directory snapshot.
    config_hash:
        SHA-256 hex of the build configuration (``.config``, recipe, …).
    env_hash:
        :func:`~osfabricum.repro.env.compute_env_hash` output.
    extra:
        Additional stable key→value pairs included in the hash.
        Do NOT put secrets or timestamps here.
    """

    step_kind: str
    source_hash: str
    config_hash: str
    env_hash: str
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_input_hash(manifest: InputManifest) -> str:
    """Return the SHA-256 hex digest of *manifest* in canonical form."""
    data = json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass
class ReproRecord:
    """Traceability record attached to a produced artifact.

    This record is typically stored in
    :attr:`~osfabricum.db.models.Artifact.metadata_json` under the key
    ``"repro"`` and/or in the :attr:`~osfabricum.db.models.Artifact.input_hash`
    column.

    Attributes
    ----------
    input_hash:
        SHA-256 of the ``InputManifest``.  Same inputs → same hash.
    env_hash:
        SHA-256 of the ``BuildEnvSpec``.
    source_hash:
        SHA-256 of the source material.
    config_hash:
        SHA-256 of the build configuration.
    step_kind:
        The job kind that produced this artifact.
    output_sha256:
        The ``Artifact.blob_sha256`` at the time of production.
    verified:
        ``True`` if a re-build with the same inputs produced the same
        ``output_sha256`` (set externally after verification run).
    """

    input_hash: str
    env_hash: str
    source_hash: str
    config_hash: str
    step_kind: str
    output_sha256: str
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_repro_record(
    manifest: InputManifest,
    output_sha256: str,
) -> ReproRecord:
    """Create a :class:`ReproRecord` from *manifest* and *output_sha256*."""
    return ReproRecord(
        input_hash=compute_input_hash(manifest),
        env_hash=manifest.env_hash,
        source_hash=manifest.source_hash,
        config_hash=manifest.config_hash,
        step_kind=manifest.step_kind,
        output_sha256=output_sha256,
    )


def verify_repro(record: ReproRecord, actual_sha256: str) -> bool:
    """Return ``True`` iff *actual_sha256* matches *record.output_sha256*.

    Parameters
    ----------
    record:
        The :class:`ReproRecord` stored with the original artifact.
    actual_sha256:
        The ``blob_sha256`` of a fresh build with the same inputs.

    Returns
    -------
    bool
        ``True`` → build is reproducible; ``False`` → outputs differ.
    """
    return record.output_sha256 == actual_sha256


def repro_record_from_dict(data: dict[str, Any]) -> ReproRecord:
    """Deserialize a :class:`ReproRecord` from a ``metadata_json["repro"]`` dict."""
    return ReproRecord(
        input_hash=data["input_hash"],
        env_hash=data["env_hash"],
        source_hash=data["source_hash"],
        config_hash=data["config_hash"],
        step_kind=data["step_kind"],
        output_sha256=data["output_sha256"],
        verified=data.get("verified", False),
    )
