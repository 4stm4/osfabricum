"""Retention policy for the artifact store (M23).

Each artifact carries a ``retention_class``.  The policy below maps a class
to a maximum age (in days) after which an *unpinned* artifact becomes
eligible for garbage collection.  ``None`` means "keep indefinitely".

ROADMAP section 5 retention classes:

================  =================  ================================
Class             Default retention  GC behaviour
================  =================  ================================
release           indefinite         explicit delete only
promoted          indefinite         explicit demotion required
permanent         indefinite         explicit delete only
staging           90 days            delete if unpinned
cache-hot         30 days            LRU within quota
cache-cold        14 days            aggressive GC
failed-run        30 days            logs kept longer than blobs
================  =================  ================================

Rules
-----
* ``pinned=True`` artifacts are **never** collected, regardless of class.
* ``release`` / ``promoted`` / ``permanent`` are never *age*-collected.
* All other classes are collected once ``created_at`` is older than the
  policy age.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

#: Maximum age in days per retention class; ``None`` = keep indefinitely.
RETENTION_POLICY: dict[str, int | None] = {
    "release": None,
    "promoted": None,
    "permanent": None,
    "staging": 90,
    "cache-hot": 30,
    "cache-cold": 14,
    "failed-run": 30,
}

#: Classes that are never collected by age (only by explicit operator action).
PROTECTED_CLASSES: frozenset[str] = frozenset({"release", "promoted", "permanent"})

#: Default age (days) for an unknown retention class — conservative.
_DEFAULT_AGE_DAYS = 90


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def retention_age_days(retention_class: str) -> int | None:
    """Return the max-age policy for *retention_class* (``None`` = forever)."""
    return RETENTION_POLICY.get(retention_class, _DEFAULT_AGE_DAYS)


def is_expired(
    retention_class: str,
    created_at: datetime | None,
    *,
    pinned: bool = False,
    now: datetime | None = None,
) -> bool:
    """Return ``True`` iff an artifact is eligible for age-based GC.

    Parameters
    ----------
    retention_class:
        The artifact's retention class.
    created_at:
        When the artifact was created (naive UTC).
    pinned:
        Pinned artifacts are never expired.
    now:
        Reference time (defaults to current UTC).
    """
    if pinned:
        return False
    if retention_class in PROTECTED_CLASSES:
        return False
    max_age = retention_age_days(retention_class)
    if max_age is None:
        return False
    if created_at is None:
        return False
    ref = now or _now()
    return created_at < (ref - timedelta(days=max_age))
