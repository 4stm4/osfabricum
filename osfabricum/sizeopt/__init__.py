"""M65 — Size / Footprint Optimizer public API."""

from osfabricum.sizeopt.service import (
    VALID_BUDGET_KINDS,
    analyze_size,
    list_size_budget_kinds,
    list_size_budgets,
    list_size_reports,
    set_size_budget,
)

__all__ = [
    "VALID_BUDGET_KINDS",
    "analyze_size",
    "list_size_budget_kinds",
    "list_size_budgets",
    "list_size_reports",
    "set_size_budget",
]
