"""Build Wizard drafts (M28).

A draft is a saved, resumable wizard session — the same shape as a
``POST /v1/plan`` / ``POST /v1/builds`` request. The wizard reads catalog data,
edits a draft, previews the plan (``POST /v1/plan``), and finally builds
(``POST /v1/builds``); nothing here builds anything.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from osfabricum.db.models import BuildDraft
from osfabricum.db.session import sync_session

_UNSET = object()


def _to_dict(draft: BuildDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "name": draft.name,
        "source_kind": draft.source_kind,
        "distribution": draft.distribution,
        "profile": draft.profile,
        "board": draft.board,
        "overrides": draft.overrides_json or {},
        "status": draft.status,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def _find(session: Session, draft_id: str) -> BuildDraft:
    draft = session.get(BuildDraft, draft_id)
    if draft is None:
        raise ValueError(f"build draft not found: {draft_id!r}")
    return draft


def create_draft(
    *,
    name: str | None = None,
    source_kind: str = "new",
    distribution: str | None = None,
    profile: str | None = None,
    board: str | None = None,
    overrides: dict[str, Any] | None = None,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        draft = BuildDraft(
            name=name,
            source_kind=source_kind,
            distribution=distribution,
            profile=profile,
            board=board,
            overrides_json=overrides,
        )
        s.add(draft)
        s.commit()
        s.refresh(draft)
        return _to_dict(draft)


def get_draft(draft_id: str, *, db_url: str | None = None) -> dict[str, Any]:
    with sync_session(db_url) as s:
        return _to_dict(_find(s, draft_id))


def list_drafts(*, db_url: str | None = None) -> list[dict[str, Any]]:
    with sync_session(db_url) as s:
        rows = s.scalars(select(BuildDraft).order_by(BuildDraft.updated_at.desc())).all()
        return [_to_dict(d) for d in rows]


def update_draft(
    draft_id: str,
    *,
    name: Any = _UNSET,
    distribution: Any = _UNSET,
    profile: Any = _UNSET,
    board: Any = _UNSET,
    overrides: Any = _UNSET,
    status: Any = _UNSET,
    db_url: str | None = None,
) -> dict[str, Any]:
    with sync_session(db_url) as s:
        draft = _find(s, draft_id)
        if name is not _UNSET:
            draft.name = name
        if distribution is not _UNSET:
            draft.distribution = distribution
        if profile is not _UNSET:
            draft.profile = profile
        if board is not _UNSET:
            draft.board = board
        if overrides is not _UNSET:
            draft.overrides_json = overrides
        if status is not _UNSET:
            draft.status = status
        s.commit()
        s.refresh(draft)
        return _to_dict(draft)


def delete_draft(draft_id: str, *, db_url: str | None = None) -> None:
    with sync_session(db_url) as s:
        s.delete(_find(s, draft_id))
        s.commit()
