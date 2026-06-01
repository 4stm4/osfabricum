"""SBOM generation for BuildPlan (M14).

Produces a CycloneDX 1.4 JSON document describing all components in a
resolved :class:`~osfabricum.resolver.plan.BuildPlan`.

``build_sbom``
    Generate an SBOM dict (JSON-serializable) from a ``BuildPlan``.

``sbom_to_bytes``
    Serialize the SBOM to stable UTF-8 JSON bytes (deterministic output).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from osfabricum.resolver.plan import BuildPlan

_CYCLONEDX_VERSION = "1.4"
_CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.4.schema.json"


def build_sbom(
    plan: BuildPlan,
    *,
    manufacturer: str = "osfabricum",
    subject_sha256: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Generate a CycloneDX 1.4 SBOM for *plan*.

    Parameters
    ----------
    plan:
        Resolved :class:`~osfabricum.resolver.plan.BuildPlan`.
    manufacturer:
        Supplier name written into ``metadata.manufacture``.
    subject_sha256:
        Optional SHA-256 of the output image/artifact — written into
        ``metadata.component.hashes``.
    timestamp:
        ISO-8601 timestamp for ``metadata.timestamp``.  When ``None``
        defaults to ``1970-01-01T00:00:00Z`` for reproducibility.

    Returns
    -------
    dict
        JSON-serializable CycloneDX 1.4 BOM.
    """
    ts = timestamp or "1970-01-01T00:00:00Z"
    bom_serial = f"urn:uuid:{uuid4()}"

    # --- metadata component (the produced image) ---
    meta_component: dict[str, Any] = {
        "type": "firmware",
        "bom-ref": f"{plan.distribution}/{plan.profile}/{plan.board}",
        "name": f"{plan.distribution}-{plan.profile}",
        "version": "latest",
        "supplier": {"name": manufacturer},
        "description": (
            f"OS image for {plan.board} ({plan.arch}), "
            f"distribution {plan.distribution!r}, profile {plan.profile!r}"
        ),
    }
    if subject_sha256:
        meta_component["hashes"] = [
            {"alg": "SHA-256", "content": subject_sha256}
        ]

    # --- components: toolchain ---
    components: list[dict[str, Any]] = []

    if plan.toolchain:
        tc = plan.toolchain
        components.append(
            {
                "type": "library",
                "bom-ref": f"toolchain/{tc.name}",
                "name": tc.name,
                "version": tc.version,
                "description": f"Cross-compilation toolchain for {tc.arch}",
                "supplier": {"name": manufacturer},
            }
        )

    # --- components: kernel ---
    if plan.kernel:
        k = plan.kernel
        components.append(
            {
                "type": "firmware",
                "bom-ref": f"kernel/{k.name}",
                "name": k.name,
                "version": k.version,
                "description": "Linux kernel",
                "supplier": {"name": manufacturer},
            }
        )

    # --- components: packages ---
    for pkg in plan.packages:
        comp: dict[str, Any] = {
            "type": "library",
            "bom-ref": f"package/{pkg.name}/{pkg.version}/{pkg.arch}",
            "name": pkg.name,
            "version": pkg.version,
            "description": f"Package for {pkg.arch}",
            "supplier": {"name": manufacturer},
        }
        if pkg.artifact_id:
            comp["externalReferences"] = [
                {
                    "type": "build-system",
                    "url": f"artifact:{pkg.artifact_id}",
                }
            ]
        components.append(comp)

    # --- components: firmware blobs ---
    for fw in plan.firmware:
        components.append(
            {
                "type": "firmware",
                "bom-ref": f"firmware/{fw.filename}",
                "name": fw.filename,
                "version": "latest",
                "description": f"Firmware blob, placement={fw.placement}",
                "supplier": {"name": manufacturer},
            }
        )

    bom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": _CYCLONEDX_VERSION,
        "$schema": _CYCLONEDX_SCHEMA,
        "serialNumber": bom_serial,
        "version": 1,
        "metadata": {
            "timestamp": ts,
            "tools": [
                {"vendor": "osfabricum", "name": "osfabricumctl", "version": "0.1.0"}
            ],
            "manufacture": {"name": manufacturer},
            "component": meta_component,
        },
        "components": components,
    }
    return bom


def sbom_to_bytes(bom: dict[str, Any]) -> bytes:
    """Serialize *bom* to stable UTF-8 JSON bytes.

    Uses ``sort_keys=True`` and consistent separators for determinism.
    The ``serialNumber`` (UUID) field will differ between calls — callers
    that need byte-identical output should fix the ``serialNumber`` before
    calling this function.
    """
    return json.dumps(bom, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8")


def sbom_hash(bom: dict[str, Any]) -> str:
    """Return the SHA-256 hex digest of the stable serialization of *bom*."""
    data = json.dumps(bom, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
