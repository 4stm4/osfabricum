"""Store filesystem layout helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_path(store_root: Path, sha256: str) -> Path:
    """Return path for a content-addressed blob: blobs/sha256/<ab>/<cd>/<full>."""
    return store_root / "blobs" / "sha256" / sha256[:2] / sha256[2:4] / sha256


def ref_path(store_root: Path, store_key: str) -> Path:
    """Return path for a human-readable ref: refs/<store_key>."""
    return store_root / "refs" / store_key
