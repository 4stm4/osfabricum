"""Runtime configuration.

Settings load from a TOML file when present and otherwise fall back to
defaults that target SQLite, so local development works with no config file.
Resolution order for the config path: explicit argument, then the
``OSFABRICUM_CONFIG`` environment variable, then the default system path.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel

DEFAULT_CONFIG_PATH = Path("/etc/osfabricum/osfabricum.toml")
ENV_CONFIG_PATH = "OSFABRICUM_CONFIG"


class DatabaseSettings(BaseModel):
    url: str = "sqlite+aiosqlite:///./osfabricum-dev.db"
    pool_size: int = 10
    max_overflow: int = 20


class StoreSettings(BaseModel):
    root: str = "/var/lib/osfabricum/store"
    work_root: str = "/var/lib/osfabricum/work"
    cache_root: str = "/var/lib/osfabricum/cache"


class QueueSettings(BaseModel):
    backend: str = "sqlite"
    prune_after_days: int = 30
    max_attempts_default: int = 3


class ApiSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"
    queue_dashboard_path: str = "/internal/queue"


class AuthSettings(BaseModel):
    enabled: bool = False
    token_header: str = "Authorization"
    token: str | None = None


class SecuritySettings(BaseModel):
    require_source_hash: bool = False
    verify_on_ingest: bool = True
    verify_on_use: bool = True
    mask_secrets_in_logs: bool = True


class TelemetrySettings(BaseModel):
    log_format: str = "json"
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    otlp_endpoint: str = ""


class WorkerSettings(BaseModel):
    max_local_workers: int = 4


class Settings(BaseModel):
    database: DatabaseSettings = DatabaseSettings()
    store: StoreSettings = StoreSettings()
    queue: QueueSettings = QueueSettings()
    api: ApiSettings = ApiSettings()
    auth: AuthSettings = AuthSettings()
    security: SecuritySettings = SecuritySettings()
    telemetry: TelemetrySettings = TelemetrySettings()
    worker: WorkerSettings = WorkerSettings()


def resolve_config_path(config_path: str | os.PathLike[str] | None = None) -> Path | None:
    """Return the config file path to load, or ``None`` if none is set/found."""
    if config_path is not None:
        return Path(config_path)
    env_path = os.environ.get(ENV_CONFIG_PATH)
    if env_path:
        return Path(env_path)
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    return None


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    """Load settings from TOML if available, otherwise use defaults (SQLite)."""
    path = resolve_config_path(config_path)
    if path is None:
        return Settings()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return Settings.model_validate(data)
