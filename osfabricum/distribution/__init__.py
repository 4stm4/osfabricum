"""Distribution Designer (M26): create/manage OS products as data.

The service layer here is the single home for distribution write logic; the
REST API (``apps/api/routes/distributions_api.py``) and the CLI
(``apps/cli/commands/distribution.py``) are thin clients over it. There is no
distribution-specific code path: a reference distribution (TinyWifi/NetOS/
Ocultum) is created, cloned, imported, and exported exactly like any other.
"""

from __future__ import annotations

from osfabricum.distribution.schema import API_VERSION, KIND, validate_doc
from osfabricum.distribution.service import (
    clone_distribution,
    create_distribution,
    delete_distribution,
    export_distribution,
    get_distribution,
    import_distribution,
    list_distributions,
    update_distribution,
)

__all__ = [
    "API_VERSION",
    "KIND",
    "clone_distribution",
    "create_distribution",
    "delete_distribution",
    "export_distribution",
    "get_distribution",
    "import_distribution",
    "list_distributions",
    "update_distribution",
    "validate_doc",
]
