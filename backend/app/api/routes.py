import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.decision_capture import CaptureError, capture_decision, rebuild_project_summary
from app.core.config import get_settings
from app.dashboard import dashboard_snapshot, list_projects
from app.intelligence import DecisionIntelligence, IntelligenceError, OfflineIntelligence, OpenAIIntelligence
from app.models import ConflictEvent, Decision, Project
from app.retrieval import get_project_context, search_project

router = APIRouter()


class LogDecisionRequest(BaseModel):
    project_id: str
    session_id: str
    exchange: str = Field(min_length=1)


class GetContextRequest(BaseModel):
    project_id: str
    session_id: str
    prompt: str = Field(min_length=1)
    fresh_session: bool = False


class SearchRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=20)


class OverrideConflictRequest(BaseModel):
    project_id: str
    reason: str = Field(min_length=3, max_length=1000)


class DeleteDecisionRequest(BaseModel):
    project_id: str


class UpdateDecisionRequest(BaseModel):
    project_id: str
    decision: str | None = Field(default=None, min_length=1, max_length=5000)
    reason: str | None = Field(default=None, min_length=1, max_length=5000)
    affected_files: list[str] | None = Field(default=None, max_length=100)


class DefaultProjectRequest(BaseModel):
    project_name: str | None = Field(default=None, min_length=1, max_length=200)


class RemoveMemoryRequest(BaseModel):
    project_id: str
    decision_ids: list[str] = Field(default_factory=list, max_length=100)
    start: datetime | None = None
    end: datetime | None = None
    delete_all: bool = False
    confirmation: str | None = Field(default=None, max_length=100)


def get_intelligence() -> DecisionIntelligence:
    """Prefer OpenAI when configured; otherwise use deterministic local behavior."""
    if OpenAIIntelligence.is_configured():
        return OpenAIIntelligence()
    return OfflineIntelligence()


def require_atlas_pin(x_atlas_dashboard_pin: Annotated[str | None, Header()] = None) -> None:
    """Require the optional local dashboard PIN for non-health API access."""
    configured = get_settings().dashboard_pin
    if configured is None:
        return
    expected = configured.get_secret_value()
    if not x_atlas_dashboard_pin or not secrets.compare_digest(x_atlas_dashboard_pin, expected):
        raise HTTPException(status_code=401, detail="Atlas dashboard PIN required")


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "atlas-api",
        "storage": get_settings().storage_mode,
        "intelligence": "openai" if OpenAIIntelligence.is_configured() else "offline",
    }


@router.post("/projects/default", tags=["projects"], dependencies=[Depends(require_atlas_pin)])
def get_or_create_default_project(
    db: Annotated[Session, Depends(get_db)],
    request: DefaultProjectRequest | None = Body(default=None),
) -> dict[str, str]:
    """Return the project requested by the calling MCP configuration."""
    settings = get_settings()
    requested_name = request.project_name if request is not None else None
    project_name = (requested_name or settings.project_name).strip()
    if not project_name:
        project_name = settings.project_name
    project = db.scalar(select(Project).where(Project.name == project_name))
    if project is None:
        project = Project(name=project_name, summary="")
        db.add(project)
        db.commit()
        db.refresh(project)
    return {"project_id": str(project.id), "project_name": project.name}


@router.get("/projects", tags=["dashboard"], dependencies=[Depends(require_atlas_pin)])
def projects(
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, list[dict[str, str]]]:
    return {"projects": list_projects(db)}


@router.get("/dashboard", tags=["dashboard"], dependencies=[Depends(require_atlas_pin)])
def dashboard(
    project_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
    db: Annotated[Session, Depends(get_db)] = None,
) -> dict[str, object]:
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="start date must not be after end date")
    try:
        settings = get_settings()
        return dashboard_snapshot(
            db,
            project_id,
            settings.storage_mode,
            "openai" if OpenAIIntelligence.is_configured() else "offline",
            start,
            end,
        )
    except CaptureError as exc:
        raise HTTPException(status_code=404 if str(exc) == "project was not found" else 400, detail=str(exc)) from exc


def _remove_memories(request: RemoveMemoryRequest, db: Session) -> dict[str, str | int]:
    try:
        project_uuid = uuid.UUID(request.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="project_id must be a UUID") from exc

    project = db.get(Project, project_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project was not found")

    has_ids = bool(request.decision_ids)
    has_range = request.start is not None or request.end is not None
    if sum((has_ids, has_range, request.delete_all)) != 1:
        raise HTTPException(status_code=400, detail="choose decision_ids, a complete date range, or delete_all")
    if has_range and (request.start is None or request.end is None):
        raise HTTPException(status_code=400, detail="both start and end are required for range removal")
    if request.delete_all and request.confirmation != "DELETE ALL PROJECT MEMORY":
        raise HTTPException(status_code=400, detail="whole-project removal requires the exact confirmation phrase")

    statement = select(Decision).where(Decision.project_id == project_uuid)
    if has_ids:
        try:
            decision_ids = list(dict.fromkeys(uuid.UUID(value) for value in request.decision_ids))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="decision_ids must contain UUIDs") from exc
        statement = statement.where(Decision.id.in_(decision_ids))
    elif has_range:
        start = request.start.replace(tzinfo=timezone.utc) if request.start.tzinfo is None else request.start.astimezone(timezone.utc)
        end = request.end.replace(tzinfo=timezone.utc) if request.end.tzinfo is None else request.end.astimezone(timezone.utc)
        if start > end:
            raise HTTPException(status_code=400, detail="start must not be after end")
        statement = statement.where(Decision.created_at >= start, Decision.created_at <= end)

    decisions = list(db.scalars(statement))
    decision_ids = [decision.id for decision in decisions]
    if request.delete_all:
        removed_conflicts = db.execute(delete(ConflictEvent).where(ConflictEvent.project_id == project_uuid)).rowcount or 0
    elif decision_ids:
        removed_conflicts = db.execute(
            delete(ConflictEvent).where(ConflictEvent.project_id == project_uuid, ConflictEvent.decision_id.in_(decision_ids))
        ).rowcount or 0
    else:
        removed_conflicts = 0

    for decision in decisions:
        db.delete(decision)
    db.flush()
    remaining = db.scalars(
        select(Decision).where(Decision.project_id == project_uuid).order_by(Decision.created_at.asc())
    ).all()
    project.summary = "\n".join(f"- {item.decision} — {item.reason}" for item in remaining[-12:])
    db.commit()
    return {
        "status": "removed",
        "project_id": request.project_id,
        "removed_decisions": len(decisions),
        "removed_conflicts": removed_conflicts,
    }


@router.delete("/decisions/{decision_id}", tags=["decisions"], dependencies=[Depends(require_atlas_pin)])
def remove_decision(
    decision_id: str,
    request: DeleteDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str | int]:
    """Permanently remove one project-scoped memory and its derived evidence."""
    return _remove_memories(RemoveMemoryRequest(project_id=request.project_id, decision_ids=[decision_id]), db)


@router.delete("/memory", tags=["decisions"], dependencies=[Depends(require_atlas_pin)])
def remove_memories(
    request: RemoveMemoryRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str | int]:
    """Remove selected memory IDs, a UTC date range, or all memory after confirmation."""
    return _remove_memories(request, db)


@router.patch("/decisions/{decision_id}", tags=["decisions"], dependencies=[Depends(require_atlas_pin)])
def update_decision(
    decision_id: str,
    request: UpdateDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    intelligence: Annotated[DecisionIntelligence, Depends(get_intelligence)],
) -> dict[str, object]:
    """Edit one saved memory while keeping retrieval and the project summary current."""
    if request.decision is None and request.reason is None and request.affected_files is None:
        raise HTTPException(status_code=400, detail="provide a decision, reason, or affected_files to update")
    if request.decision is not None and not request.decision.strip():
        raise HTTPException(status_code=400, detail="decision cannot be blank")
    if request.reason is not None and not request.reason.strip():
        raise HTTPException(status_code=400, detail="reason cannot be blank")
    try:
        project_uuid = uuid.UUID(request.project_id)
        memory_uuid = uuid.UUID(decision_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="decision_id and project_id must be UUIDs") from exc

    project = db.get(Project, project_uuid)
    decision = db.get(Decision, memory_uuid)
    if project is None:
        raise HTTPException(status_code=404, detail="project was not found")
    if decision is None or decision.project_id != project_uuid:
        raise HTTPException(status_code=404, detail="decision was not found for this project")

    if request.decision is not None:
        decision.decision = request.decision.strip()
    if request.reason is not None:
        decision.reason = request.reason.strip()
    if request.affected_files is not None:
        decision.affected_files = list(dict.fromkeys(path.strip().replace("\\", "/") for path in request.affected_files if path.strip()))

    try:
        decision.embedding = intelligence.embed(decision.decision, decision.reason)
        project.summary = rebuild_project_summary(db, intelligence, project)
        db.commit()
        db.refresh(decision)
        return {
            "status": "updated",
            "project_id": request.project_id,
            "decision": {
                "id": str(decision.id),
                "decision": decision.decision,
                "reason": decision.reason,
                "affected_files": decision.affected_files,
            },
            "running_summary": project.summary,
        }
    except IntelligenceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/decisions/log", tags=["decisions"], dependencies=[Depends(require_atlas_pin)])
def log_decision(
    request: LogDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    intelligence: Annotated[DecisionIntelligence, Depends(get_intelligence)],
) -> dict[str, str | bool | None]:
    try:
        return capture_decision(db, intelligence, request.project_id, request.session_id, request.exchange).as_dict()
    except CaptureError as exc:
        db.rollback()
        raise HTTPException(status_code=404 if str(exc) == "project was not found" else 400, detail=str(exc)) from exc
    except IntelligenceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/context", tags=["context"], dependencies=[Depends(require_atlas_pin)])
def get_context(
    request: GetContextRequest,
    db: Annotated[Session, Depends(get_db)],
    intelligence: Annotated[DecisionIntelligence, Depends(get_intelligence)],
) -> dict[str, object]:
    try:
        return get_project_context(
            db, intelligence, request.project_id, request.session_id, request.prompt, request.fresh_session
        )
    except CaptureError as exc:
        raise HTTPException(status_code=404 if str(exc) == "project was not found" else 400, detail=str(exc)) from exc


@router.post("/search", tags=["context"], dependencies=[Depends(require_atlas_pin)])
def search(
    request: SearchRequest,
    db: Annotated[Session, Depends(get_db)],
    intelligence: Annotated[DecisionIntelligence, Depends(get_intelligence)],
) -> dict[str, object]:
    try:
        return search_project(db, intelligence, request.project_id, request.query, request.limit)
    except CaptureError as exc:
        raise HTTPException(status_code=404 if str(exc) == "project was not found" else 400, detail=str(exc)) from exc


@router.post("/conflicts/{conflict_event_id}/override", tags=["conflicts"], dependencies=[Depends(require_atlas_pin)])
def override_conflict(
    conflict_event_id: str,
    request: OverrideConflictRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    try:
        event_id = uuid.UUID(conflict_event_id)
        project_id = uuid.UUID(request.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="conflict_event_id and project_id must be UUIDs") from exc

    event = db.get(ConflictEvent, event_id)
    if event is None or event.project_id != project_id:
        raise HTTPException(status_code=404, detail="conflict event was not found for this project")
    if event.status == "overridden":
        raise HTTPException(status_code=409, detail="conflict event has already been overridden")

    event.status = "overridden"
    event.override_reason = request.reason.strip()
    event.overridden_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "status": event.status,
        "conflict_event_id": str(event.id),
        "project_id": request.project_id,
        "override_reason": event.override_reason,
    }
