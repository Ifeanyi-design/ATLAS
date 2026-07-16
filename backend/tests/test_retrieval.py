import uuid
from datetime import datetime, timezone

import pytest

from app.decision_capture import CaptureError
from app.intelligence import OfflineIntelligence
from app.models import ConflictEvent, Decision, DesignContext, Project, SessionRecord
from app.retrieval import get_project_context, search_project


class FakeContextDb:
    def __init__(self, project: Project, batches: list[list[object]]) -> None:
        self.project = project
        self.batches = batches
        self.added: list[object] = []
        self.commits = 0

    def get(self, model: type[object], identifier: uuid.UUID) -> object | None:
        return self.project if model is Project and identifier == self.project.id else None

    def scalars(self, _statement: object) -> list[object]:
        return self.batches.pop(0)

    def add(self, item: object) -> None:
        self.added.append(item)

    def commit(self) -> None:
        self.commits += 1


class NeverEmbed:
    def embed(self, *_args: object) -> list[float]:
        raise AssertionError("fresh sessions must not retrieve or embed")

    def curate(self, *_args: object) -> list[str]:
        raise AssertionError("fresh sessions must not curate")


def test_fresh_session_returns_no_memory_without_model_work() -> None:
    project = Project(id=uuid.uuid4(), name="atlas", summary="Existing project summary")
    db = FakeContextDb(project, [])

    result = get_project_context(db, NeverEmbed(), str(project.id), str(uuid.uuid4()), "Build a dashboard", True)

    assert result["status"] == "fresh_session"
    assert result["running_summary"] is None
    assert result["decisions"] == []


def test_context_rejects_a_session_owned_by_another_project() -> None:
    project = Project(id=uuid.uuid4(), name="atlas")
    foreign_session = SessionRecord(id=uuid.uuid4(), project_id=uuid.uuid4())

    class CrossProjectDb(FakeContextDb):
        def get(self, model: type[object], identifier: uuid.UUID) -> object | None:
            if model is SessionRecord and identifier == foreign_session.id:
                return foreign_session
            return super().get(model, identifier)

    with pytest.raises(CaptureError, match="different project"):
        get_project_context(
            CrossProjectDb(project, []), NeverEmbed(), str(project.id), str(foreign_session.id), "Build a dashboard", False
        )


def test_offline_retrieval_curates_relevant_decisions_and_ui_context() -> None:
    project = Project(id=uuid.uuid4(), name="atlas", summary="Cards are part of the visual language.")
    decision = Decision(
        id=uuid.uuid4(),
        project_id=project.id,
        decision="Use compact cards for the checkout screen.",
        reason="The checkout layout needs a scannable mobile hierarchy.",
        affected_files=["app/checkout.tsx"],
        embedding=[0.0] * 1536,
        created_at=datetime.now(timezone.utc),
    )
    context = DesignContext(
        id=uuid.uuid4(),
        project_id=project.id,
        decision_id=decision.id,
        context={"spacing": {"card": 8}},
        file_paths=["app/checkout.tsx"],
    )
    db = FakeContextDb(project, [[decision], [context]])

    result = get_project_context(
        db,
        OfflineIntelligence(),
        str(project.id),
        str(uuid.uuid4()),
        "Update the checkout screen UI layout.",
        False,
    )

    assert result["candidate_count"] == 1
    assert result["decisions"][0]["id"] == str(decision.id)
    assert result["design_context"][0]["context"] == {"spacing": {"card": 8}}


def _database_decision(project_id: uuid.UUID) -> Decision:
    return Decision(
        id=uuid.uuid4(),
        project_id=project_id,
        decision="Use PostgreSQL for persistence.",
        reason="It supports pgvector retrieval.",
        affected_files=["backend/app/models.py"],
        embedding=[0.0] * 1536,
        created_at=datetime.now(timezone.utc),
    )


def test_offline_conflict_detection_persists_clear_reversal() -> None:
    project = Project(id=uuid.uuid4(), name="atlas")
    decision = _database_decision(project.id)
    db = FakeContextDb(project, [[decision]])

    result = get_project_context(
        db, OfflineIntelligence(), str(project.id), str(uuid.uuid4()), "Replace PostgreSQL with MySQL.", False
    )

    assert result["conflict"]["has_conflict"] is True
    assert result["conflict"]["original_decision"] == decision.decision
    assert any(isinstance(item, ConflictEvent) for item in db.added)
    assert db.commits == 1


def test_offline_conflict_detection_allows_refinements_and_ignores_unrelated_prompts() -> None:
    project = Project(id=uuid.uuid4(), name="atlas")
    decision = _database_decision(project.id)

    refinement = get_project_context(
        FakeContextDb(project, [[decision]]),
        OfflineIntelligence(),
        str(project.id),
        str(uuid.uuid4()),
        "Add an index to PostgreSQL for faster reads.",
        False,
    )
    unrelated = get_project_context(
        FakeContextDb(project, [[decision]]),
        OfflineIntelligence(),
        str(project.id),
        str(uuid.uuid4()),
        "Replace the dashboard background image.",
        False,
    )

    assert refinement["conflict"]["has_conflict"] is False
    assert unrelated["conflict"]["has_conflict"] is False


def test_search_returns_scoped_vector_candidates() -> None:
    project = Project(id=uuid.uuid4(), name="atlas")
    decision = _database_decision(project.id)

    result = search_project(FakeContextDb(project, [[decision]]), OfflineIntelligence(), str(project.id), "PostgreSQL", 99)

    assert result["limit"] == 20
    assert result["results"][0]["id"] == str(decision.id)
