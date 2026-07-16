import uuid

from app.api.routes import OverrideConflictRequest, override_conflict
from app.models import ConflictEvent


class FakeConflictDb:
    def __init__(self, event: ConflictEvent) -> None:
        self.event = event
        self.commits = 0

    def get(self, model: type[object], identifier: uuid.UUID) -> object | None:
        return self.event if model is ConflictEvent and identifier == self.event.id else None

    def commit(self) -> None:
        self.commits += 1


def test_conflict_override_requires_and_records_a_reason() -> None:
    project_id = uuid.uuid4()
    event = ConflictEvent(
        id=uuid.uuid4(),
        project_id=project_id,
        new_intent="Use a new persistence approach.",
        explanation="This conflicts with the recorded database decision.",
    )
    db = FakeConflictDb(event)

    result = override_conflict(
        str(event.id),
        OverrideConflictRequest(project_id=str(project_id), reason="The project is now single-user and offline-first."),
        db,  # type: ignore[arg-type]
    )

    assert result["status"] == "overridden"
    assert event.override_reason == "The project is now single-user and offline-first."
    assert event.overridden_at is not None
    assert db.commits == 1
