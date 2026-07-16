from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.decision_capture import CaptureError, _parse_uuid
from app.models import ConflictEvent, Decision, DesignContext, Project


def _estimate_tokens(value: object) -> int:
    """A transparent, provider-independent token estimate for dashboard scenarios."""
    if not value:
        return 0
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))
    return math.ceil(len(text) / 4)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _range_conditions(column: Any, start: datetime | None, end: datetime | None) -> list[Any]:
    conditions: list[Any] = []
    if normalized_start := _as_utc(start):
        conditions.append(column >= normalized_start)
    if normalized_end := _as_utc(end):
        conditions.append(column <= normalized_end)
    return conditions


def list_projects(db: Session) -> list[dict[str, str]]:
    projects = db.scalars(select(Project).order_by(Project.name)).all()
    return [{"id": str(project.id), "name": project.name} for project in projects]


def dashboard_snapshot(
    db: Session,
    project_id: str,
    storage_mode: str,
    intelligence_mode: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, object]:
    project_uuid = _parse_uuid(project_id, "project_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise CaptureError("project was not found")

    decision_conditions = [Decision.project_id == project_uuid, *_range_conditions(Decision.created_at, start, end)]
    decisions = db.scalars(select(Decision).where(*decision_conditions).order_by(Decision.created_at.desc())).all()

    conflict_conditions = [ConflictEvent.project_id == project_uuid, *_range_conditions(ConflictEvent.created_at, start, end)]
    conflicts = db.scalars(select(ConflictEvent).where(*conflict_conditions).order_by(ConflictEvent.created_at.desc())).all()
    all_decisions = db.scalars(
        select(Decision).where(Decision.project_id == project_uuid).order_by(Decision.created_at.desc())
    ).all()
    decision_by_id = {decision.id: decision for decision in all_decisions}

    design_conditions = [DesignContext.project_id == project_uuid, *_range_conditions(DesignContext.created_at, start, end)]
    design_contexts = db.scalars(select(DesignContext).where(*design_conditions).order_by(DesignContext.created_at.desc())).all()

    summary_tokens = _estimate_tokens(project.summary)
    all_decision_tokens = sum(_estimate_tokens(f"{decision.decision}\n{decision.reason}") for decision in all_decisions)
    full_history_tokens = summary_tokens + all_decision_tokens
    focused_decisions = all_decisions[:6]
    focused_tokens = summary_tokens + sum(
        _estimate_tokens(f"{decision.decision}\n{decision.reason}") for decision in focused_decisions
    )

    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "summary": project.summary or "No decisions recorded yet.",
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
        },
        "system": {
            "storage": storage_mode,
            "storage_detail": (
                "SQLite keeps this project local and ranks JSON embeddings in-process."
                if storage_mode == "sqlite"
                else "PostgreSQL uses pgvector for indexed shared-project retrieval."
            ),
            "intelligence": intelligence_mode,
        },
        "filters": {"start": _as_utc(start).isoformat() if start else None, "end": _as_utc(end).isoformat() if end else None},
        "counts": {
            "total_decisions": len(all_decisions),
            "visible_decisions": len(decisions),
            "visible_conflicts": len(conflicts),
            "visible_design_contexts": len(design_contexts),
        },
        "decisions": [
            {
                "id": str(decision.id),
                "decision": decision.decision,
                "reason": decision.reason,
                "affected_files": decision.affected_files,
                "created_at": decision.created_at.isoformat(),
            }
            for decision in decisions
        ],
        "conflicts": [
            {
                "id": str(conflict.id),
                "status": conflict.status,
                "new_intent": conflict.new_intent,
                "explanation": conflict.explanation,
                "prior_decision": decision_by_id.get(conflict.decision_id).decision if conflict.decision_id in decision_by_id else None,
                "override_reason": conflict.override_reason,
                "overridden_at": conflict.overridden_at.isoformat() if conflict.overridden_at else None,
                "created_at": conflict.created_at.isoformat(),
            }
            for conflict in conflicts
        ],
        "design_context": [
            {
                "decision_id": str(context.decision_id) if context.decision_id else None,
                "context": context.context,
                "file_paths": context.file_paths,
                "created_at": context.created_at.isoformat(),
            }
            for context in design_contexts
        ],
        "token_estimate": {
            "full_history_baseline": full_history_tokens,
            "fresh_session_avoided": full_history_tokens,
            "focused_context_budget": focused_tokens,
            "focused_context_avoided": max(full_history_tokens - focused_tokens, 0),
            "method": "Estimated as serialized character count divided by four. This excludes output tokens, model reasoning, and provider cache effects.",
        },
    }
