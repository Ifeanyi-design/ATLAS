from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.intelligence import DecisionIntelligence
from app.models import Decision, DesignContext, Project, SessionRecord


class CaptureError(ValueError):
    """Raised when a log_decision request cannot be persisted safely."""


@dataclass(frozen=True)
class CaptureResult:
    accepted: bool
    status: str
    project_id: str
    session_id: str
    decision_id: str | None = None
    running_summary: str | None = None

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "accepted": self.accepted,
            "status": self.status,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "decision_id": self.decision_id,
            "running_summary": self.running_summary,
        }


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise CaptureError(f"{field_name} must be a UUID") from exc


def capture_decision(
    db: Session,
    intelligence: DecisionIntelligence,
    project_id: str,
    session_id: str,
    exchange: str,
) -> CaptureResult:
    project_uuid = _parse_uuid(project_id, "project_id")
    session_uuid = _parse_uuid(session_id, "session_id")
    project = db.get(Project, project_uuid)
    if project is None:
        raise CaptureError("project was not found")

    session = db.get(SessionRecord, session_uuid)
    if session is not None and session.project_id != project_uuid:
        raise CaptureError("session belongs to a different project")

    extraction = intelligence.extract(exchange)
    if not extraction.is_real_decision:
        return CaptureResult(False, "no_decision", project_id, session_id)

    assert extraction.decision is not None
    assert extraction.reason is not None
    embedding = intelligence.embed(extraction.decision, extraction.reason)
    running_summary = intelligence.update_summary(project.summary, extraction.decision, extraction.reason)

    if session is None:
        session = SessionRecord(id=session_uuid, project_id=project_uuid)
        db.add(session)

    decision = Decision(
        project_id=project_uuid,
        session_id=session_uuid,
        decision=extraction.decision,
        reason=extraction.reason,
        affected_files=extraction.affected_files,
        embedding=embedding,
    )
    db.add(decision)
    db.flush()

    if extraction.design_context is not None:
        db.add(
            DesignContext(
                project_id=project_uuid,
                decision_id=decision.id,
                context=extraction.design_context,
                file_paths=extraction.affected_files,
            )
        )

    project.summary = running_summary
    db.commit()
    return CaptureResult(True, "stored", project_id, session_id, str(decision.id), running_summary)
