"""Reproducibility model (M13) — build env spec and hash chain."""

from osfabricum.repro.chain import (
    InputManifest,
    ReproRecord,
    compute_input_hash,
    make_repro_record,
    repro_record_from_dict,
    verify_repro,
)
from osfabricum.repro.env import (
    PROTECTED_ENV_VARS,
    SOURCE_DATE_EPOCH,
    BuildEnvSpec,
    compute_env_hash,
    make_reproducible_env,
)

__all__ = [
    # env
    "PROTECTED_ENV_VARS",
    "SOURCE_DATE_EPOCH",
    "BuildEnvSpec",
    "compute_env_hash",
    "make_reproducible_env",
    # chain
    "InputManifest",
    "ReproRecord",
    "compute_input_hash",
    "make_repro_record",
    "repro_record_from_dict",
    "verify_repro",
]
