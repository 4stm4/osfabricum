"""Reproducible build environment specification (M13).

All build steps that produce artifacts MUST use a frozen environment.
This module is the single source of truth for what "frozen" means.

``BuildEnvSpec``
    Describes the immutable parts of the build environment.

``compute_env_hash``
    Deterministic SHA-256 of a ``BuildEnvSpec``.

``make_reproducible_env``
    Merge frozen env vars into an existing environment dict, returning a
    new dict where ``SOURCE_DATE_EPOCH``, ``KBUILD_*``, and related vars
    always have their frozen values regardless of the host environment.

Design notes
------------
* ``SOURCE_DATE_EPOCH=0`` is the canonical value — corresponds to
  1970-01-01 00:00:00 UTC, which is supported by all known build tools
  that honour this variable.
* ``KBUILD_BUILD_TIMESTAMP`` / ``KBUILD_BUILD_USER`` / ``KBUILD_BUILD_HOST``
  are Linux kernel-specific but are frozen here globally so kernel and
  package builds are consistent.
* Locale vars (``LANG``, ``LC_ALL``) are always forced to ``C`` so
  tool output is deterministic regardless of the host locale.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Canonical frozen values
# ---------------------------------------------------------------------------

SOURCE_DATE_EPOCH: int = 0
KBUILD_BUILD_TIMESTAMP: str = "Thu Jan  1 00:00:00 UTC 1970"
KBUILD_BUILD_USER: str = "osfabricum"
KBUILD_BUILD_HOST: str = "osfabricum"

#: Env vars that are *always* overridden in a reproducible build.
#: These cannot be set by callers via ``env_extra``; they are constants.
PROTECTED_ENV_VARS: frozenset[str] = frozenset(
    {
        "SOURCE_DATE_EPOCH",
        "KBUILD_BUILD_TIMESTAMP",
        "KBUILD_BUILD_USER",
        "KBUILD_BUILD_HOST",
        "LANG",
        "LC_ALL",
        "TZ",
    }
)


# ---------------------------------------------------------------------------
# BuildEnvSpec
# ---------------------------------------------------------------------------


@dataclass
class BuildEnvSpec:
    """Immutable description of the build environment for one build step.

    Attributes
    ----------
    arch:
        Target architecture string (e.g. ``"aarch64"``).
    toolchain_id:
        UUID of the :class:`~osfabricum.db.models.Toolchain` row, or
        ``None`` for native builds.
    toolchain_version:
        Version string of the toolchain (e.g. ``"13.2.0"``).
    cross_compile_prefix:
        ``CROSS_COMPILE`` value (e.g. ``"aarch64-linux-musl-"``).
    extra_frozen:
        Additional key→value pairs that should be frozen.  These are
        included in the hash but must not contain secrets.
    """

    arch: str = ""
    toolchain_id: str | None = None
    toolchain_version: str | None = None
    cross_compile_prefix: str = ""
    extra_frozen: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_env_hash(spec: BuildEnvSpec) -> str:
    """Return the SHA-256 hex digest of *spec* in canonical form.

    The hash covers the spec fields plus the frozen constant values
    (``SOURCE_DATE_EPOCH``, etc.) so a change to any constant is visible
    in the hash.
    """
    payload: dict[str, Any] = {
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "kbuild_timestamp": KBUILD_BUILD_TIMESTAMP,
        "kbuild_user": KBUILD_BUILD_USER,
        "kbuild_host": KBUILD_BUILD_HOST,
        **spec.to_dict(),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def make_reproducible_env(
    spec: BuildEnvSpec,
    *,
    path_extra: list[str] | None = None,
    env_extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a full environment dict for a reproducible build step.

    Parameters
    ----------
    spec:
        The build environment specification.
    path_extra:
        Additional directories prepended to ``PATH`` (e.g. toolchain bin).
    env_extra:
        Caller-supplied extra env vars.  Values for keys in
        :data:`PROTECTED_ENV_VARS` are silently ignored.

    Returns
    -------
    dict[str, str]
        A new environment dict.  Does NOT inherit the current process
        environment — callers must add ``HOME`` etc. themselves if needed.
    """
    from pathlib import Path

    path_parts: list[str] = list(path_extra or [])
    path_parts.extend(["/usr/bin", "/bin"])

    env: dict[str, str] = {}

    # Apply caller extras first (protected vars will be overridden below)
    for k, v in (env_extra or {}).items():
        if k not in PROTECTED_ENV_VARS:
            env[k] = str(v)

    # Frozen vars — always win
    env.update(
        {
            "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH),
            "KBUILD_BUILD_TIMESTAMP": KBUILD_BUILD_TIMESTAMP,
            "KBUILD_BUILD_USER": KBUILD_BUILD_USER,
            "KBUILD_BUILD_HOST": KBUILD_BUILD_HOST,
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "PATH": ":".join(path_parts),
        }
    )

    # Architecture / cross-compile
    if spec.arch:
        env["ARCH"] = spec.arch
    if spec.cross_compile_prefix:
        env["CROSS_COMPILE"] = spec.cross_compile_prefix

    # Minimum usability (HOME is required by many tools)
    env.setdefault("HOME", str(Path.home()))

    return env
