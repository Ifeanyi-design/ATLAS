from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings
from app.intelligence import OpenAIIntelligence


def test_health_check() -> None:
    assert TestClient(app).get("/api/v1/health").json() == {
        "status": "ok",
        "service": "atlas-api",
        "storage": get_settings().storage_mode,
        "intelligence": "openai" if OpenAIIntelligence.is_configured() else "offline",
    }


def test_default_project_is_created_once_for_project_local_mcp_calls() -> None:
    with TestClient(app) as client:
        first = client.post("/api/v1/projects/default")
        second = client.post("/api/v1/projects/default")

    assert first.status_code == 200
    assert first.json()["project_id"] == second.json()["project_id"]


def test_dashboard_is_served_and_returns_a_transparent_empty_snapshot() -> None:
    with TestClient(app) as client:
        project = client.post("/api/v1/projects/default").json()
        dashboard = client.get(f"/api/v1/dashboard?project_id={project['project_id']}")
        page = client.get("/dashboard/")

    assert dashboard.status_code == 200
    assert dashboard.json()["token_estimate"]["method"].startswith("Estimated")
    assert page.status_code == 200
    assert "Decision intelligence" in page.text
