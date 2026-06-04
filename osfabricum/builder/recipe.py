"""Recipe executor — hash, cache-check, and multi-phase build runner (M8).

Entry points
------------
:func:`compute_recipe_hash`
    Derive a deterministic hex-digest from build_system + steps + env + toolchain.

:func:`run_recipe`
    Execute all four driver phases and return a :class:`RecipeResult`.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from osfabricum.builder.context import BuildContext
from osfabricum.db.models import Artifact
from osfabricum.db.session import sync_session
from osfabricum.repro.chain import InputManifest, compute_input_hash, make_repro_record
from osfabricum.repro.env import BuildEnvSpec, compute_env_hash
from osfabricum.store.ingest import ingest_blob

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RecipeResult:
    """Outcome of a :func:`run_recipe` call."""

    #: ``True`` when all phases completed without error.
    success: bool

    #: SHA-256 hex digest of the recipe specification.
    recipe_hash: str

    #: Captured stdout/stderr lines from all subprocesses.
    logs: list[str] = field(default_factory=list)

    #: ``Artifact.id`` of the ingested build output (``None`` on failure).
    artifact_id: str | None = None

    #: ``True`` when the result was served from the store without rebuilding.
    cache_hit: bool = False

    #: Human-readable error message on failure; ``None`` on success.
    error: str | None = None

    #: Preserved work directory on failure (``None`` on success / cleanup).
    work_dir: Path | None = None


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------


def compute_recipe_hash(
    build_system: str,
    steps: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    toolchain_id: str | None = None,
) -> str:
    """Return a deterministic SHA-256 hex digest of the recipe specification.

    Parameters
    ----------
    build_system:
        One of ``cargo``, ``make``, ``cmake``, ``meson``, ``autotools``, ``custom``.
    steps:
        Parsed ``steps_json`` from the :class:`~osfabricum.db.models.BuildRecipe`.
    env:
        Extra environment variables from ``env_json``.
    toolchain_id:
        Toolchain UUID or name included in the hash so that a toolchain
        upgrade invalidates the cached result.
    """
    payload = {
        "build_system": build_system,
        "steps": steps or {},
        "env": env or {},
        "toolchain_id": toolchain_id or "",
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _make_build_env(
    env_extra: dict[str, str] | None,
    toolchain_root: Path | None,
    destdir: Path,
) -> dict[str, str]:
    """Build the subprocess environment for all driver phases.

    * ``SOURCE_DATE_EPOCH=0`` is always set (reproducibility).
    * ``DESTDIR`` is always set to the staging root.
    * ``PATH`` is restricted to ``toolchain/bin:/usr/bin:/bin``.
    * Extra environment keys from the recipe are merged last but cannot
      override ``SOURCE_DATE_EPOCH`` or ``DESTDIR``.
    """
    path_parts: list[str] = []
    if toolchain_root is not None:
        path_parts.append(str(toolchain_root / "bin"))
    path_parts.extend(["/usr/bin", "/bin"])

    env: dict[str, str] = {
        "PATH": ":".join(path_parts),
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": str(Path.home()),
    }

    # Merge recipe-level extras (before protected keys so they cannot win)
    for k, v in (env_extra or {}).items():
        env[k] = str(v)

    # Protected — always override any recipe value
    env["SOURCE_DATE_EPOCH"] = "0"
    env["DESTDIR"] = str(destdir)

    return env


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_recipe(
    *,
    build_system: str,
    steps: dict[str, Any] | None = None,
    env_extra: dict[str, str] | None = None,
    src_dir: Path,
    store_root: Path,
    toolchain_root: Path | None = None,
    toolchain_id: str | None = None,
    source_hash: str | None = None,
    db_url: str | None = None,
) -> RecipeResult:
    """Fetch, build, and cache a single recipe.

    Steps
    -----
    1. Compute ``recipe_hash`` from the recipe specification.
    2. Check the store for a cached result keyed on
       ``recipe/<recipe_hash>/<source_hash>/output``.
    3. Select the appropriate :class:`~osfabricum.builder.drivers.base.BuildDriver`.
    4. Create an isolated ``work_dir`` and a ``destdir`` staging root.
    5. Inject ``SOURCE_DATE_EPOCH=0``, ``DESTDIR``, and restricted ``PATH``
       into the process environment.
    6. Run ``prepare → configure → build → install`` via the driver.
    7. Pack ``destdir`` into a ``.tar.gz`` and ingest via
       :func:`~osfabricum.store.ingest.ingest_blob`.
    8. Clean up the work directory on success; preserve it on failure.

    Parameters
    ----------
    build_system:
        Build system identifier (``cargo``/``make``/``cmake``/``meson``/
        ``autotools``/``custom``).
    steps:
        Phase commands keyed by phase name (``prepare``, ``configure``,
        ``build``, ``install``).
    env_extra:
        Extra environment variables to inject.  Cannot override
        ``SOURCE_DATE_EPOCH`` or ``DESTDIR``.
    src_dir:
        Root of the already-extracted source tree.
    store_root:
        Root of the content-addressed artifact store.
    toolchain_root:
        Optional toolchain prefix — its ``bin/`` directory is prepended to
        ``PATH``.
    toolchain_id:
        Toolchain identifier included in the hash (so upgrades invalidate
        the cache).
    source_hash:
        SHA-256 of the source artifact, included in the cache key.
    db_url:
        SQLAlchemy database URL.  Cache check is skipped when ``None``.

    Returns
    -------
    RecipeResult
        ``success=True`` with ``artifact_id`` set on success, or
        ``success=False`` with ``error`` and ``work_dir`` preserved on failure.
    """
    from osfabricum.builder.drivers import DRIVERS

    recipe_hash = compute_recipe_hash(build_system, steps, env_extra, toolchain_id)
    cache_key = f"recipe/{recipe_hash}/{source_hash or 'nosrc'}/output"

    # --- cache hit ---
    if db_url is not None:
        with sync_session(db_url) as session:
            existing = session.scalar(select(Artifact).where(Artifact.store_key == cache_key))
            if existing is not None:
                return RecipeResult(
                    success=True,
                    recipe_hash=recipe_hash,
                    logs=[],
                    artifact_id=existing.id,
                    cache_hit=True,
                )

    if build_system not in DRIVERS:
        raise ValueError(f"unsupported build_system: {build_system!r}")

    driver = DRIVERS[build_system]()

    # --- work directories ---
    work_tmp = tempfile.mkdtemp(prefix="osfab-build-")
    work_dir = Path(work_tmp)
    destdir = work_dir / "destdir"
    destdir.mkdir()

    build_env = _make_build_env(env_extra, toolchain_root, destdir)
    logs: list[str] = []
    ctx = BuildContext(
        src_dir=src_dir,
        work_dir=work_dir,
        destdir=destdir,
        env=build_env,
        steps=steps or {},
        logs=logs,
    )

    # --- run phases ---
    try:
        driver.prepare(ctx)
        driver.configure(ctx)
        driver.build(ctx)
        driver.install(ctx)
    except Exception as exc:
        # Preserve work_dir so the operator can inspect the failure
        return RecipeResult(
            success=False,
            recipe_hash=recipe_hash,
            logs=logs,
            work_dir=work_dir,
            error=str(exc),
        )

    # --- pack destdir and ingest ---
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if destdir.exists() and any(destdir.iterdir()):
            tar.add(str(destdir), arcname="destdir")
    data = buf.getvalue()

    # --- reproducibility chain (M13) ---
    import hashlib as _hashlib  # noqa: PLC0415

    _env_spec = BuildEnvSpec(
        toolchain_id=toolchain_id,
    )
    _env_hash = compute_env_hash(_env_spec)
    _manifest = InputManifest(
        step_kind="package.build",
        source_hash=source_hash or "",
        config_hash=recipe_hash,
        env_hash=_env_hash,
    )
    _input_hash = compute_input_hash(_manifest)
    _repro_rec = make_repro_record(_manifest, _hashlib.sha256(data).hexdigest())

    artifact = ingest_blob(
        data=data,
        store_root=store_root,
        store_key=cache_key,
        kind="build-output",
        name=f"recipe/{recipe_hash[:16]}",
        version=None,
        media_type="application/x-gzip",
        db_url=db_url,
        retention_class="cache-hot",
        input_hash=_input_hash,
        repro_record=_repro_rec,
    )

    # --- clean up on success ---
    shutil.rmtree(work_tmp, ignore_errors=True)

    return RecipeResult(
        success=True,
        recipe_hash=recipe_hash,
        logs=logs,
        artifact_id=artifact.id,
        cache_hit=False,
    )
