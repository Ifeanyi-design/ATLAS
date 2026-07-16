import uuid

import pytest

from app.decision_capture import CaptureError, capture_decision
from app.extraction import DecisionExtraction
from app.models import Decision, Project, SessionRecord


class FakeIntelligence:
    def __init__(self, extraction: DecisionExtraction) -> None:
        self.extraction = extraction
        self.embed_calls = 0
        self.summary_calls = 0

    def extract(self, exchange: str) -> DecisionExtraction:
        return self.extraction

    def embed(self, decision: str, reason: str) -> list[float]:
        self.embed_calls += 1
        return [0.25, 0.75]

    def update_summary(self, current_summary: str | None, decision: str, reason: str) -> str:
        self.summary_calls += 1
        return f"{current_summary or ''} {decision}".strip()


class FakeSession:
    def __init__(self, project: Project, session: SessionRecord | None = None) -> None:
        self.project = project
        self.session = session
        self.added: list[object] = []
        self.commits = 0

    def get(self, model: type[object], identifier: uuid.UUID) -> object | None:
        if model is Project:
            return self.project if identifier == self.project.id else None
        if model is SessionRecord:
            return self.session if self.session is not None and identifier == self.session.id else None
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    def flush(self) -> None:
        for item in self.added:
            if isinstance(item, Decision) and item.id is None:
                item.id = uuid.uuid4()

    def commit(self) -> None:
        self.commits += 1


def real_extraction() -> DecisionExtraction:
    return DecisionExtraction(
        is_real_decision=True,
        decision="Keep decision records project-scoped.",
        reason="Project memories must not leak between teams.",
        affected_files=["backend/app/models.py"],
        design_context={"spacing": {"card": 8}},
    )


def test_capture_persists_decision_design_context_embedding_and_summary() -> None:
    project = Project(id=uuid.uuid4(), name="atlas")
    db = FakeSession(project)
    intelligence = FakeIntelligence(real_extraction())
    session_id = uuid.uuid4()

    result = capture_decision(db, intelligence, str(project.id), str(session_id), "Use project scoping.")

    assert result.accepted is True
    assert result.status == "stored"
    assert result.decision_id is not None
    assert project.summary == "Keep decision records project-scoped."
    assert intelligence.embed_calls == 1
    assert intelligence.summary_calls == 1
    assert db.commits == 1
    assert any(isinstance(item, Decision) for item in db.added)
    assert any(isinstance(item, SessionRecord) for item in db.added)
    design_context = next(item for item in db.added if item.__class__.__name__ == "DesignContext")
    assert design_context.file_paths == ["backend/app/models.py"]


def test_capture_stores_nothing_for_non_decision() -> None:
    project = Project(id=uuid.uuid4(), name="atlas")
    db = FakeSession(project)
    intelligence = FakeIntelligence(DecisionExtraction(is_real_decision=False))

    result = capture_decision(db, intelligence, str(project.id), str(uuid.uuid4()), "Ran tests.")

    assert result.status == "no_decision"
    assert db.added == []
    assert db.commits == 0
    assert intelligence.embed_calls == 0
    assert intelligence.summary_calls == 0


def test_capture_rejects_session_from_another_project_before_model_calls() -> None:
    project = Project(id=uuid.uuid4(), name="atlas")
    session = SessionRecord(id=uuid.uuid4(), project_id=uuid.uuid4())
    db = FakeSession(project, session)
    intelligence = FakeIntelligence(real_extraction())

    with pytest.raises(CaptureError, match="different project"):
        capture_decision(db, intelligence, str(project.id), str(session.id), "Use project scoping.")

    assert intelligence.embed_calls == 0
    assert intelligence.summary_calls == 0
