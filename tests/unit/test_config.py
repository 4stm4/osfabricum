from pathlib import Path

from osfabricum.config import load_settings


def test_defaults_use_sqlite(monkeypatch) -> None:
    monkeypatch.delenv("OSFABRICUM_CONFIG", raising=False)
    settings = load_settings()
    assert settings.database.url.startswith("sqlite")
    assert settings.auth.enabled is False


def test_load_from_toml(tmp_path: Path) -> None:
    cfg = tmp_path / "osfabricum.toml"
    cfg.write_text('[api]\nport = 9001\n[database]\nurl = "sqlite+aiosqlite:///./x.db"\n')
    settings = load_settings(cfg)
    assert settings.api.port == 9001
    assert settings.database.url.endswith("x.db")
