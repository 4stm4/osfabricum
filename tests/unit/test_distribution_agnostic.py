"""M24/M25 invariant: the OSFabricum core is distribution-agnostic.

CI grep gate for anti-patterns #1–#3 (ROADMAP §18c — *Core Invariants &
Anti-Patterns*): no code in ``osfabricum/`` or ``apps/`` may branch on a
reference-distribution name. Reference distributions (TinyWifi, NetOS, Ocultum)
are data records and validation profiles, never code paths.

This guard is what keeps the audit's headline property true over time. It is
deliberately precise (it matches equality/branch comparisons against a
distribution name, not incidental string mentions such as docstrings/examples)
so it has no false positives on the current tree.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_ROOTS = (REPO_ROOT / "osfabricum", REPO_ROOT / "apps")

# Equality / branch comparisons against a reference distribution name.
_FORBIDDEN = re.compile(
    r"""(?xi)
      (?: (?:==|!=) \s* ["'] (?:tinywifi|netos|ocultum) ["'] )   # == "tinywifi"
    | (?: ["'] (?:tinywifi|netos|ocultum) ["'] \s* (?:==|!=) )   # "tinywifi" ==
    | (?: \b if \s+ distribution \s* == )                        # if distribution ==
    """
)


def _py_files() -> list[Path]:
    files: list[Path] = []
    for root in CODE_ROOTS:
        files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def test_code_roots_exist() -> None:
    for root in CODE_ROOTS:
        assert root.is_dir(), f"missing code root: {root}"


def test_no_distribution_name_branches() -> None:
    offenders: list[str] = []
    for path in _py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "distribution-name branch found (anti-pattern #1–#3):\n" + "\n".join(
        offenders
    )
