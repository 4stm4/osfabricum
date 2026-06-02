"""M24 doc-lint: the audit/roadmap docs are internally consistent.

Covers the M24 — *Implementation Audit & Gap Matrix* test criteria:

* the three deliverables exist and are non-empty,
* every internal markdown link in the top-level docs resolves,
* the audit mentions every milestone M0–M23,
* every per-milestone ``**Status**`` uses only the allowed vocabulary.

These are the "doc-lint only" tests the milestone specifies; they keep the
documentation honest as the universal roadmap (M24+) evolves.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

# Top-level universal-roadmap docs in scope for M24.
DOC_FILES = sorted(DOCS.glob("*.md"))

M24_DELIVERABLES = ("IMPLEMENTATION_AUDIT.md", "GAPS.md", "NEXT_ACTIONS.md")

STATUS_VOCABULARY = {
    "done",
    "partial",
    "missing",
    "implemented-but-not-tested",
    "documented-only",
    "needs-redesign",
    "needs-hardening",
}

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_LINE_REF_RE = re.compile(r":\d+(?:-\d+)?$")


def _resolve(doc: Path, target: str) -> bool:
    """Return ``True`` if *target* (from *doc*) points at an existing path."""
    target = target.split("#", 1)[0]
    if not target:
        return True  # pure in-page anchor
    target = _LINE_REF_RE.sub("", target)  # drop a trailing :line ref
    return any((base / target).exists() for base in (doc.parent, REPO_ROOT))


def test_doc_files_present() -> None:
    assert DOC_FILES, "no docs/*.md found"


@pytest.mark.parametrize("name", M24_DELIVERABLES)
def test_m24_deliverable_exists(name: str) -> None:
    path = DOCS / name
    assert path.is_file(), f"missing M24 deliverable: docs/{name}"
    assert path.read_text(encoding="utf-8").strip(), f"empty deliverable: docs/{name}"


def test_all_internal_links_resolve() -> None:
    broken: list[str] = []
    for doc in DOC_FILES:
        for target in _LINK_RE.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not _resolve(doc, target):
                broken.append(f"{doc.relative_to(REPO_ROOT)} -> {target}")
    assert not broken, "unresolved internal doc links:\n" + "\n".join(broken)


def test_audit_covers_m0_through_m23() -> None:
    text = (DOCS / "IMPLEMENTATION_AUDIT.md").read_text(encoding="utf-8")
    missing = [f"M{n}" for n in range(24) if not re.search(rf"\bM{n}\b", text)]
    assert not missing, f"audit does not mention: {missing}"


def test_status_vocabulary_is_consistent() -> None:
    """Every backtick token on a per-milestone ``**Status**`` line is allowed."""
    text = (DOCS / "IMPLEMENTATION_AUDIT.md").read_text(encoding="utf-8")
    offenders: set[str] = set()
    for line in text.splitlines():
        if "**Status**" not in line:
            continue
        for token in _BACKTICK_RE.findall(line):
            if token not in STATUS_VOCABULARY:
                offenders.add(token)
    assert not offenders, f"non-vocabulary status tokens: {sorted(offenders)}"
