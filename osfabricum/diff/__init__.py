"""M59 — Build / Profile / Release Diff public API."""

from osfabricum.diff.service import (
    VALID_DIFF_KINDS,
    VALID_ENTITY_KINDS,
    create_diff_report,
    get_diff_report,
    list_diff_report_kinds,
    list_diff_reports,
    render_diff_report,
)

__all__ = [
    "VALID_DIFF_KINDS",
    "VALID_ENTITY_KINDS",
    "create_diff_report",
    "get_diff_report",
    "list_diff_report_kinds",
    "list_diff_reports",
    "render_diff_report",
]
