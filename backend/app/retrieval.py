from __future__ import annotations

import re
import uuid
from datetime import datetime
from math import sqrt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.decision_capture import CaptureError, _parse_uuid
from app.intelligence import ContextIntelligence
from app.models import ConflictEvent, Decision, DesignContext, Project, SessionRecord

_UI_TERMS = {"ui", "ux", "design", "screen", "layout", "color", "colour", "spacing", "typography", "component", "style"}
_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(value.lower()))


def _is_ui_prompt(prompt: str) -> bool:
    return bool(_tokens(prompt) & _UI_TERMS)


def _candidate(decision: Decision) -> dict[str, Any]:
    return {
        "id": str(decision.id),
        "decision": decision.decision,
        "reason": decision.reason,
        "affected_files": decision.affected_files,
        "created_at": decision.created_at.isoformat() if decision.created_at else datetime.min.isoformat(),
    }


def _validate_project_and_session(db: Session, project_id: str, session_id: str | None = None) -> tuple[Project, uuid.UUID]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise CaptureError("project was not found")
    if session_id is not None:
        session_uuid = _parse_uuid(session_id, "session_id")
        session = db.get(SessionRecord, session_uuid)
        if session is not None and session.project_id != project_uuid:
            raise CaptureError("session belongs to a different project")
    return project, project_uuid


def _uses_sqlite(db: Session) -> bool:
    dialect = getattr(getattr(db, "bind", None), "dialect", None)
    return dialect is not None and dialect.name == "sqlite"


def _cosine_distance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return float("inf")
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    if denominator == 0:
        return float("inf")
    return 1 - sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _vector_candidates(db: Session, project_uuid: uuid.UUID, embedding: list[float], limit: int) -> list[Decision]:
    limit = min(max(limit, 1), 20)
    if _uses_sqlite(db):
        statement = select(Decision).where(Decision.project_id == project_uuid, Decision.embedding.is_not(None))
        candidates = list(db.scalars(statement))
        return sorted(
            candidates,
            key=lambda decision: (_cosine_distance(embedding, decision.embedding or []), str(decision.id)),
        )[:limit]

    statement = (
        select(Decision)
        .where(Decision.project_id == project_uuid, Decision.embedding.is_not(None))
        .order_by(Decision.embedding.cosine_distance(embedding), Decision.id)
        .limit(limit)
    )
    return list(db.scalars(statement))


def search_project(
    db: Session, intelligence: ContextIntelligence, project_id: str, query: str, limit: int = 10
) -> dict[str, Any]:
    _, project_uuid = _validate_project_and_session(db, project_id)
    results = [_candidate(decision) for decision in _vector_candidates(db, project_uuid, intelligence.embed(query), limit)]
    return {"status": "ok", "project_id": project_id, "query": query, "limit": min(max(limit, 1), 20), "results": results}


def get_project_context(
    db: Session,
    intelligence: ContextIntelligence,
    project_id: str,
    session_id: str,
    prompt: str,
    fresh_session: bool,
    candidate_limit: int = 20,
    selected_limit: int = 6,
) -> dict[str, Any]:
    project, project_uuid = _validate_project_and_session(db, project_id, session_id)

    base = {
        "status": "fresh_session" if fresh_session else "ok",
        "project_id": project_id,
        "session_id": session_id,
        "fresh_session": fresh_session,
        "running_summary": None,
        "decisions": [],
        "design_context": [],
        "conflict": None,
        "candidate_count": 0,
    }
    if fresh_session:
        return base

    candidates = _vector_candidates(db, project_uuid, intelligence.embed(prompt), min(max(candidate_limit, 15), 20))
    candidate_payloads = [_candidate(candidate) for candidate in candidates]
    selected_ids = intelligence.curate(prompt, candidate_payloads, selected_limit)
    selected = sorted(
        (candidate for candidate in candidate_payloads if candidate["id"] in selected_ids),
        key=lambda candidate: candidate["id"],
    )

    base["running_summary"] = project.summary
    base["decisions"] = selected
    base["candidate_count"] = len(candidate_payloads)

    conflict = intelligence.detect_conflict(prompt, selected)
    if conflict["has_conflict"]:
        event = ConflictEvent(
            project_id=project_uuid,
            decision_id=uuid.UUID(conflict["original_id"]),
            new_intent=conflict["new_intent"],
            explanation=conflict["explanation"],
        )
        db.add(event)
        flush = getattr(db, "flush", None)
        if callable(flush):
            flush()
        db.commit()
        conflict["event_id"] = str(event.id) if event.id is not None else None
        conflict["status"] = event.status
        conflict.pop("original_id", None)
    base["conflict"] = conflict

    if _is_ui_prompt(prompt) and selected_ids:
        design_statement = select(DesignContext).where(
            DesignContext.project_id == project_uuid,
            DesignContext.decision_id.in_([uuid.UUID(value) for value in selected_ids]),
        ).order_by(DesignContext.decision_id)
        base["design_context"] = [
            {"decision_id": str(context.decision_id), "context": context.context, "file_paths": context.file_paths}
            for context in db.scalars(design_statement)
        ]
    return base
