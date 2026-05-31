"""Entry point for ``osfabricum-api``."""

from __future__ import annotations

import uvicorn

from osfabricum.settings import load_settings
from osfabricum.logging import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings.telemetry.log_format, settings.api.log_level)
    uvicorn.run(
        "apps.api.app:app",
        host=settings.api.host,
        port=settings.api.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
