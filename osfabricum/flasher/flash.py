"""Image flashing with verification (M21).

``flash_image_artifact``
    Load an ``image`` artifact (``.img.gz``) from the store, decompress it,
    and write it to a target device — but only if the device is on the
    allowlist.  Optionally verifies the write by reading back and comparing
    SHA-256.

``flash_image_bytes``
    Lower-level: flash raw decompressed image bytes to a device path.

Safety
------
* The device must match the allowlist (see
  :func:`~osfabricum.flasher.device.is_device_allowed`).
* ``dry_run=True`` performs all checks and reports the plan without writing
  a single byte.
* Writes are done in fixed-size blocks; progress is reported via the
  returned ``FlashResult.logs``.
"""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.flasher.device import is_device_allowed
from osfabricum.store.layout import blob_path

#: Block size for writing / verifying (4 MiB).
BLOCK_SIZE = 4 * 1024 * 1024


@dataclass
class FlashResult:
    """Outcome of a flash operation."""

    success: bool
    device: str
    bytes_written: int = 0
    image_sha256: str | None = None
    verified: bool = False
    dry_run: bool = False
    error: str | None = None
    logs: list[str] = field(default_factory=list)


def _decompress_if_gzip(data: bytes) -> bytes:
    """Return decompressed bytes if *data* is gzip, else *data* unchanged."""
    if data[:2] == b"\x1f\x8b":  # gzip magic
        return gzip.decompress(data)
    return data


def flash_image_bytes(
    image_data: bytes,
    device: str,
    *,
    allowlist: tuple[str, ...] | list[str],
    dry_run: bool = False,
    verify: bool = True,
    block_size: int = BLOCK_SIZE,
) -> FlashResult:
    """Write *image_data* (already decompressed) to *device*.

    Parameters
    ----------
    image_data:
        Raw image bytes to write.
    device:
        Target device path (e.g. ``/dev/sdb`` or, in tests, a regular file).
    allowlist:
        Glob patterns of permitted device paths.
    dry_run:
        When ``True`` validate and report only; do not write.
    verify:
        When ``True`` read the device back and compare SHA-256.
    block_size:
        Write/verify block size in bytes.
    """
    logs: list[str] = []
    image_sha256 = hashlib.sha256(image_data).hexdigest()
    logs.append(f"[flash] image size: {len(image_data)} bytes, sha256={image_sha256[:16]}…")

    # --- safety: allowlist check ---
    if not is_device_allowed(device, allowlist):
        return FlashResult(
            success=False,
            device=device,
            image_sha256=image_sha256,
            error=(
                f"device {device!r} is not on the allowlist "
                f"(allowlist={list(allowlist)!r}); refusing to write"
            ),
            logs=logs,
        )

    if dry_run:
        logs.append(f"[flash] DRY RUN — would write {len(image_data)} bytes to {device}")
        return FlashResult(
            success=True,
            device=device,
            bytes_written=0,
            image_sha256=image_sha256,
            dry_run=True,
            logs=logs,
        )

    # --- write ---
    try:
        written = 0
        with open(device, "wb") as dev:  # noqa: PTH123
            for off in range(0, len(image_data), block_size):
                chunk = image_data[off : off + block_size]
                dev.write(chunk)
                written += len(chunk)
            dev.flush()
        logs.append(f"[flash] wrote {written} bytes to {device}")
    except OSError as exc:
        return FlashResult(
            success=False,
            device=device,
            image_sha256=image_sha256,
            error=f"write failed: {exc}",
            logs=logs,
        )

    # --- verify ---
    verified = False
    if verify:
        try:
            h = hashlib.sha256()
            remaining = len(image_data)
            with open(device, "rb") as dev:  # noqa: PTH123
                while remaining > 0:
                    chunk = dev.read(min(block_size, remaining))
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
            readback = h.hexdigest()
            verified = readback == image_sha256
            if verified:
                logs.append("[flash] verify OK — readback sha256 matches")
            else:
                logs.append(
                    f"[flash] verify FAILED — expected {image_sha256[:16]}…, "
                    f"got {readback[:16]}…"
                )
                return FlashResult(
                    success=False,
                    device=device,
                    bytes_written=written,
                    image_sha256=image_sha256,
                    verified=False,
                    error="verification failed: readback sha256 mismatch",
                    logs=logs,
                )
        except OSError as exc:
            return FlashResult(
                success=False,
                device=device,
                bytes_written=written,
                image_sha256=image_sha256,
                error=f"verify read failed: {exc}",
                logs=logs,
            )

    return FlashResult(
        success=True,
        device=device,
        bytes_written=written,
        image_sha256=image_sha256,
        verified=verified,
        logs=logs,
    )


def flash_image_artifact(
    artifact_id: str,
    device: str,
    *,
    store_root: Path,
    allowlist: tuple[str, ...] | list[str],
    dry_run: bool = False,
    verify: bool = True,
    db_url: str | None = None,
) -> FlashResult:
    """Flash an ``image`` artifact from the store to *device*.

    The artifact blob (typically ``.img.gz``) is loaded, decompressed if
    gzip-compressed, and written to the device.

    Parameters
    ----------
    artifact_id:
        UUID of the ``image`` artifact.
    device:
        Target device path.
    store_root:
        Artifact store root.
    allowlist:
        Permitted device path globs.
    dry_run:
        Validate and report only.
    verify:
        Read back and compare SHA-256.
    db_url:
        SQLAlchemy database URL.
    """
    logs: list[str] = []

    with sync_session(db_url) as session:
        art: Artifact | None = session.scalar(
            select(Artifact).where(Artifact.id == artifact_id)
        )
        if art is None:
            return FlashResult(
                success=False,
                device=device,
                error=f"artifact not found: {artifact_id!r}",
                logs=logs,
            )
        sha256 = art.blob_sha256
        name = art.name
        kind = art.kind

    if kind != "image":
        logs.append(f"[flash] WARNING: artifact kind is {kind!r}, expected 'image'")

    bp = blob_path(store_root, sha256)
    if not bp.exists():
        return FlashResult(
            success=False,
            device=device,
            error=f"blob not found for artifact {artifact_id}: {bp}",
            logs=logs,
        )

    logs.append(f"[flash] artifact {name} ({artifact_id[:8]}…)")
    raw = bp.read_bytes()
    image_data = _decompress_if_gzip(raw)
    if len(image_data) != len(raw):
        logs.append(f"[flash] decompressed {len(raw)} → {len(image_data)} bytes")

    result = flash_image_bytes(
        image_data,
        device,
        allowlist=allowlist,
        dry_run=dry_run,
        verify=verify,
    )
    # Prepend artifact-loading logs
    result.logs = logs + result.logs
    return result
