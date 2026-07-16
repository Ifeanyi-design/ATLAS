import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.dashboard import dashboard_snapshot
from app.db import Base
from app.models import ConflictEvent, Decision, DesignContext, Project
from app.retrieval import _vector_candidates
from app.api.routes import DeleteDecisionRequest, RemoveMemoryRequest, remove_decision, remove_memories


def test_sqlite_schema_stores_json_embeddings_and_ranks_locally() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: object, _: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    Base.metadata.create_all(engine)
    project = Project(id=uuid.uuid4(), name="sqlite-atlas")
    with Session(engine) as db:
        db.add(project)
        db.add_all(
            [
                Decision(project_id=project.id, decision="Use SQLite locally.", reason="No Docker.", embedding=[1.0, 0.0]),
                Decision(project_id=project.id, decision="Use PostgreSQL for teams.", reason="Shared access.", embedding=[0.0, 1.0]),
            ]
        )
        db.commit()

        candidates = _vector_candidates(db, project.id, [1.0, 0.0], 2)

    assert [candidate.decision for candidate in candidates] == [
        "Use SQLite locally.",
        "Use PostgreSQL for teams.",
    ]


def test_dashboard_snapshot_exposes_decisions_conflicts_design_and_estimates() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    project = Project(id=uuid.uuid4(), name="dashboard-atlas", summary="Use a local-first setup.")

    with Session(engine) as db:
        db.add(project)
        db.commit()
        decision = Decision(
            project_id=project.id,
            decision="Use PostgreSQL for shared deployments.",
            reason="Teams need a shared indexed memory store.",
            affected_files=["backend/app/models.py"],
            embedding=[1.0, 0.0],
        )
        db.add(decision)
        db.flush()
        db.add(
            ConflictEvent(
                project_id=project.id,
                decision_id=decision.id,
                new_intent="Replace the shared store.",
                explanation="The request contradicts the team deployment decision.",
                status="overridden",
                override_reason="This test project is local-only.",
            )
        )
        db.add(
            DesignContext(
                project_id=project.id,
                decision_id=decision.id,
                context={"color": {"accent": "mint"}},
                file_paths=["dashboard/styles.css"],
            )
        )
        db.commit()

        snapshot = dashboard_snapshot(db, str(project.id), "sqlite", "offline")

    assert snapshot["system"]["storage"] == "sqlite"
    assert snapshot["decisions"][0]["decision"] == "Use PostgreSQL for shared deployments."
    assert snapshot["conflicts"][0]["override_reason"] == "This test project is local-only."
    assert snapshot["design_context"][0]["context"] == {"color": {"accent": "mint"}}
    assert snapshot["token_estimate"]["fresh_session_avoided"] > 0
    assert snapshot["counts"]["total_decisions"] == 1


def test_removing_memory_is_project_scoped_and_cleans_derived_evidence() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    project = Project(id=uuid.uuid4(), name="removal-atlas", summary="- Remove this memory — Test cleanup.")

    with Session(engine) as db:
        db.add(project)
        db.commit()
        decision = Decision(project_id=project.id, decision="Remove this memory.", reason="Test cleanup.", embedding=[1.0])
        db.add(decision)
        db.flush()
        db.add(DesignContext(project_id=project.id, decision_id=decision.id, context={"color": "mint"}))
        db.add(
            ConflictEvent(
                project_id=project.id,
                decision_id=decision.id,
                new_intent="Replace this memory.",
                explanation="The test asks for its removal.",
            )
        )
        db.commit()

        result = remove_decision(str(decision.id), DeleteDecisionRequest(project_id=str(project.id)), db)

        assert result["status"] == "removed"
        assert db.get(Decision, decision.id) is None
        assert list(db.scalars(select(DesignContext))) == []
        assert list(db.scalars(select(ConflictEvent))) == []
        assert db.get(Project, project.id).summary == ""


def test_bulk_memory_removal_supports_ids_ranges_and_whole_project_confirmation() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    first_project = Project(id=uuid.uuid4(), name="bulk-removal-atlas")
    second_project = Project(id=uuid.uuid4(), name="other-atlas")
    first_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
    second_time = datetime(2026, 7, 2, tzinfo=timezone.utc)

    with Session(engine) as db:
        db.add_all([first_project, second_project])
        db.flush()
        first = Decision(project_id=first_project.id, decision="First selected memory.", reason="Test list removal.", embedding=[1.0], created_at=first_time)
        second = Decision(project_id=first_project.id, decision="Second range memory.", reason="Test range removal.", embedding=[1.0], created_at=second_time)
        other = Decision(project_id=second_project.id, decision="Other project memory.", reason="Project isolation.", embedding=[1.0])
        db.add_all([first, second, other])
        db.commit()

        listed = remove_memories(RemoveMemoryRequest(project_id=str(first_project.id), decision_ids=[str(first.id)]), db)
        assert listed["removed_decisions"] == 1
        assert db.get(Decision, first.id) is None

        ranged = remove_memories(RemoveMemoryRequest(project_id=str(first_project.id), start="2026-07-01T12:00:00Z", end="2026-07-02T12:00:00Z"), db)
        assert ranged["removed_decisions"] == 1
        assert db.get(Decision, second.id) is None
        assert db.get(Decision, other.id) is not None

        removed_all = remove_memories(RemoveMemoryRequest(project_id=str(second_project.id), delete_all=True, confirmation="DELETE ALL PROJECT MEMORY"), db)
        assert removed_all["removed_decisions"] == 1
        assert db.get(Decision, other.id) is None
