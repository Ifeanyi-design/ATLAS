import atexit
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

# The MCP process starts at the repository root, while FastAPI lives in backend/.
BACKEND_PATH = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.core.config import get_settings

mcp = FastMCP("Atlas")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_started_api: subprocess.Popen[bytes] | None = None
_default_project_id: str | None = None
_default_session_id = str(uuid.uuid4())


def _api_is_available() -> bool:
    try:
        with urlopen(f"{get_settings().api_url.rstrip('/')}/api/v1/health", timeout=1) as response:
            return response.status == 200
    except (HTTPError, URLError):
        return False


def _headers(content_type: bool = True) -> dict[str, str]:
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = "application/json"
    dashboard_pin = get_settings().dashboard_pin
    if dashboard_pin is not None:
        headers["X-Atlas-Dashboard-Pin"] = dashboard_pin.get_secret_value()
    return headers


def _stop_started_api() -> None:
    if _started_api is not None and _started_api.poll() is None:
        _started_api.terminate()


def _find_docker_command() -> str | None:
    configured = os.environ.get("ATLAS_DOCKER_COMMAND")
    if configured:
        return configured
    return shutil.which("docker")


def ensure_managed_local_postgres() -> None:
    """Restore the Docker database chosen as Atlas-managed local storage."""
    settings = get_settings()
    database = urlparse(settings.database_url)
    is_managed_local_postgres = (
        settings.storage_mode == "postgres"
        and settings.auto_start_docker
        and database.hostname in {"127.0.0.1", "localhost"}
        and database.port == 5434
    )
    docker_command = _find_docker_command()
    if not is_managed_local_postgres or docker_command is None:
        return
    try:
        subprocess.run(
            [docker_command, "compose", "up", "-d", "--wait", "db"],
            cwd=PROJECT_ROOT,
            check=True,
            timeout=60,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return


def ensure_local_api() -> None:
    """Start the local API only when Atlas owns it and it is not already running."""
    global _started_api
    settings = get_settings()
    ensure_managed_local_postgres()
    if _api_is_available():
        return

    parsed = urlparse(settings.api_url)
    if not settings.auto_start_api or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    bind_host = settings.api_host
    if bind_host not in {"127.0.0.1", "localhost"} and settings.dashboard_pin is None:
        print(
            "Atlas warning: the dashboard API is bound to a non-local address "
            f"({bind_host}) with no ATLAS_DASHBOARD_PIN set. Anyone on the network "
            "can read or delete memory. Set ATLAS_DASHBOARD_PIN before exposing Atlas "
            "beyond this machine.",
            file=sys.stderr,
        )
    log_path = PROJECT_ROOT / "work" / "atlas-api.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    _started_api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            str(PROJECT_ROOT / "backend"),
            "--host",
            bind_host,
            "--port",
            str(port),
        ],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    atexit.register(_stop_started_api)

    for _ in range(120):
        time.sleep(0.25)
        if _api_is_available():
            return
        if _started_api.poll() is not None:
            break
    raise RuntimeError(f"Atlas could not start its local API. See {log_path}.")


def _resolve_project_name() -> str:
    """Pick the Atlas project name for this Codex session.

    Codex injects CODEX_WORKSPACE_ROOT (the active project folder) into the MCP
    server environment, so different Codex projects isolate their memory even
    though a single global MCP server entry serves them all. Fall back to the
    configured ATLAS_PROJECT_NAME (set by `atlas attach`) and finally to the
    install's default project name.
    """
    workspace = os.environ.get("CODEX_WORKSPACE_ROOT")
    if workspace:
        name = Path(workspace).resolve().name
        if name:
            return name
    env_name = os.environ.get("ATLAS_PROJECT_NAME")
    if env_name:
        return env_name
    return get_settings().project_name


def _project_id(project_id: str | None = None, project_name: str | None = None) -> str:
    global _default_project_id
    if project_id:
        return project_id
    if project_name:
        payload = json.dumps({"project_name": project_name}).encode()
        request = Request(
            f"{get_settings().api_url.rstrip('/')}/api/v1/projects/default",
            data=payload,
            headers=_headers(),
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            return str(json.loads(response.read().decode())["project_id"])
    if _default_project_id:
        return _default_project_id
    payload = json.dumps({"project_name": _resolve_project_name()}).encode()
    request = Request(
        f"{get_settings().api_url.rstrip('/')}/api/v1/projects/default",
        data=payload,
        headers=_headers(),
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        _default_project_id = str(json.loads(response.read().decode())["project_id"])
    return _default_project_id


def _session_id(session_id: str | None) -> str:
    return session_id or _default_session_id


@mcp.tool()
def log_decision(exchange: str, project_id: str | None = None, session_id: str | None = None, project_name: str | None = None) -> dict[str, Any]:
    """Extract and persist a material engineering decision; project/session IDs are automatic by default."""
    ensure_local_api()
    resolved_project_id = _project_id(project_id, project_name)
    resolved_session_id = _session_id(session_id)
    payload = json.dumps({"project_id": resolved_project_id, "session_id": resolved_session_id, "exchange": exchange}).encode()
    request = Request(
        f"{get_settings().api_url.rstrip('/')}/api/v1/decisions/log",
        data=payload,
        headers=_headers(),
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode()
        return {"accepted": False, "status": "error", "project_id": resolved_project_id, "session_id": resolved_session_id, "message": detail}
    except URLError as exc:
        return {"accepted": False, "status": "unavailable", "project_id": resolved_project_id, "session_id": resolved_session_id, "message": str(exc.reason)}


@mcp.tool()
def get_context(prompt: str, fresh_session: bool = False, project_id: str | None = None, session_id: str | None = None, project_name: str | None = None) -> dict[str, Any]:
    """Get scoped context before work; IDs are automatic unless a specific project/session is supplied."""
    ensure_local_api()
    resolved_project_id = _project_id(project_id, project_name)
    resolved_session_id = _session_id(session_id)
    payload = json.dumps(
        {"project_id": resolved_project_id, "session_id": resolved_session_id, "prompt": prompt, "fresh_session": fresh_session}
    ).encode()
    request = Request(
        f"{get_settings().api_url.rstrip('/')}/api/v1/context",
        data=payload,
        headers=_headers(),
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode()
        return {"status": "error", "project_id": resolved_project_id, "session_id": resolved_session_id, "message": detail}
    except URLError as exc:
        return {"status": "unavailable", "project_id": resolved_project_id, "session_id": resolved_session_id, "message": str(exc.reason)}


@mcp.tool()
def search(query: str, limit: int = 10, project_id: str | None = None, project_name: str | None = None) -> dict[str, Any]:
    """Explicitly recall relevant project decisions; the current project is automatic by default."""
    ensure_local_api()
    resolved_project_id = _project_id(project_id, project_name)
    payload = json.dumps({"project_id": resolved_project_id, "query": query, "limit": min(max(limit, 1), 20)}).encode()
    request = Request(
        f"{get_settings().api_url.rstrip('/')}/api/v1/search",
        data=payload,
        headers=_headers(),
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode()
        return {"status": "error", "project_id": resolved_project_id, "query": query, "message": detail}
    except URLError as exc:
        return {"status": "unavailable", "project_id": resolved_project_id, "query": query, "message": str(exc.reason)}


@mcp.tool()
def remove_memory(
    decision_id: str | None = None,
    decision_ids: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    delete_all: bool = False,
    confirmation: str | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Remove selected memories, a UTC time range, or all project memory with exact confirmation."""
    ensure_local_api()
    resolved_project_id = _project_id(project_id, project_name)
    selected_ids = list(decision_ids or [])
    if decision_id is not None:
        selected_ids.append(decision_id)
    request = Request(
        f"{get_settings().api_url.rstrip('/')}/api/v1/memory",
        data=json.dumps(
            {
                "project_id": resolved_project_id,
                "decision_ids": selected_ids,
                "start": start,
                "end": end,
                "delete_all": delete_all,
                "confirmation": confirmation,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="DELETE",
    )
    request.headers.update(_headers(content_type=False))
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode()
        return {"status": "error", "project_id": resolved_project_id, "message": detail}
    except URLError as exc:
        return {"status": "unavailable", "project_id": resolved_project_id, "message": str(exc.reason)}


@mcp.tool()
def edit_memory(
    decision_id: str,
    decision: str | None = None,
    reason: str | None = None,
    affected_files: list[str] | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Edit a known saved memory by ID. Use search first when you need to find its ID."""
    ensure_local_api()
    resolved_project_id = _project_id(project_id, project_name)
    payload = json.dumps(
        {
            "project_id": resolved_project_id,
            "decision": decision,
            "reason": reason,
            "affected_files": affected_files,
        }
    ).encode()
    request = Request(
        f"{get_settings().api_url.rstrip('/')}/api/v1/decisions/{decision_id}",
        data=payload,
        headers=_headers(),
        method="PATCH",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode()
        return {"status": "error", "project_id": resolved_project_id, "decision_id": decision_id, "message": detail}
    except URLError as exc:
        return {"status": "unavailable", "project_id": resolved_project_id, "decision_id": decision_id, "message": str(exc.reason)}


@mcp.tool()
def override_conflict(conflict_event_id: str, reason: str, project_id: str | None = None, project_name: str | None = None) -> dict[str, Any]:
    """Record a deliberate, explained decision to continue despite an Atlas conflict warning."""
    ensure_local_api()
    resolved_project_id = _project_id(project_id, project_name)
    payload = json.dumps({"project_id": resolved_project_id, "reason": reason}).encode()
    request = Request(
        f"{get_settings().api_url.rstrip('/')}/api/v1/conflicts/{conflict_event_id}/override",
        data=payload,
        headers=_headers(),
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode()
        return {"status": "error", "project_id": resolved_project_id, "conflict_event_id": conflict_event_id, "message": detail}
    except URLError as exc:
        return {"status": "unavailable", "project_id": resolved_project_id, "conflict_event_id": conflict_event_id, "message": str(exc.reason)}


if __name__ == "__main__":
    mcp.run()
