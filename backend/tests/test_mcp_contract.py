import json
from types import SimpleNamespace

from mcp_server import server
from mcp_server.server import edit_memory, get_context, log_decision, remove_memory, search


def test_tool_contracts_are_stable(monkeypatch) -> None:
    class Response:
        def read(self) -> bytes:
            return json.dumps({"accepted": True, "status": "stored"}).encode()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(server, "urlopen", lambda _request, timeout: Response())
    monkeypatch.setattr(server, "ensure_local_api", lambda: None)

    assert log_decision("Chosen FastAPI", project_id="p", session_id="s")["status"] == "stored"
    assert get_context("Add route", project_id="p", session_id="s")["status"] == "stored"
    assert search("database", 99, project_id="p")["status"] == "stored"
    assert remove_memory("decision-id", project_id="p")["status"] == "stored"
    assert edit_memory("decision-id", reason="Updated reason", project_id="p")["status"] == "stored"


def test_mcp_default_project_request_sends_configured_project_name(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        def read(self) -> bytes:
            return json.dumps({"project_id": "project-1"}).encode()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(request, timeout):
        captured["data"] = json.loads(request.data.decode())
        captured["headers"] = dict(request.headers)
        return Response()

    monkeypatch.setattr(server, "urlopen", fake_urlopen)
    monkeypatch.setattr(server, "ensure_local_api", lambda: None)
    monkeypatch.setattr(server, "_default_project_id", None)
    monkeypatch.setattr(server, "get_settings", lambda: SimpleNamespace(project_name="bizlive-dashboard", dashboard_pin=None, api_url="http://127.0.0.1:8000"))

    assert server._project_id(None) == "project-1"
    assert captured["data"] == {"project_name": "bizlive-dashboard"}


def test_managed_local_postgres_starts_docker_after_restart(monkeypatch) -> None:
    calls: list[tuple[list[str], object]] = []
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(
            storage_mode="postgres",
            auto_start_docker=True,
            database_url="postgresql+psycopg://atlas:atlas@127.0.0.1:5434/atlas",
        ),
    )
    monkeypatch.setattr(server, "_find_docker_command", lambda: "docker")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs.get("cwd"))),
    )

    server.ensure_managed_local_postgres()

    assert calls == [(["docker", "compose", "up", "-d", "--wait", "db"], server.PROJECT_ROOT)]
