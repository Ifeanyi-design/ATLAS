r"""Atlas environment doctor.

Run from the project root with:

    .venv\Scripts\python.exe backend\scripts\doctor.py
"""

from __future__ import annotations

import json
import importlib.util
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from setup import CODEX_CONFIG_PATH, PROJECT_ROOT, REQUIRED_MODULES, docker_is_ready, find_docker_command


BACKEND_PATH = PROJECT_ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


failures = 0
warnings = 0


def _print(status: str, message: str) -> None:
    print(f"[{status}] {message}")


def pass_(message: str) -> None:
    _print("PASS", message)


def warn(message: str) -> None:
    global warnings
    warnings += 1
    _print("WARN", message)


def fail(message: str) -> None:
    global failures
    failures += 1
    _print("FAIL", message)


def redact_database_url(url: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:<redacted>@", url)


def check_python() -> None:
    if sys.version_info >= (3, 11):
        pass_(f"Python {sys.version.split()[0]} is supported.")
    else:
        fail(f"Python {sys.version.split()[0]} is too old; use Python 3.11 or newer.")
    if sys.prefix == sys.base_prefix:
        fail("Python is not running inside a virtual environment.")
    else:
        pass_("Python is running inside a virtual environment.")


def check_dependencies() -> None:
    missing = [module for module in REQUIRED_MODULES if importlib.util.find_spec(module) is None]
    if missing:
        fail("Missing Python dependencies: " + ", ".join(missing))
    else:
        pass_("Python dependencies are importable.")


def check_codex_config() -> None:
    if not CODEX_CONFIG_PATH.exists():
        fail(".codex/config.toml is missing; rerun setup.")
        return
    content = CODEX_CONFIG_PATH.read_text(encoding="utf-8")
    if "[mcp_servers.atlas]" not in content:
        fail(".codex/config.toml does not register the Atlas MCP server.")
        return
    if "mcp_server.server" not in content:
        fail(".codex/config.toml has an Atlas entry, but it does not point at mcp_server.server.")
        return
    pass_(".codex/config.toml registers the Atlas MCP server.")


def check_mcp_handshake() -> None:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "atlas-doctor", "version": "0"},
        },
    }
    started = time.monotonic()
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "mcp_server.server"],
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert process.stdin is not None
        assert process.stdout is not None
        output: queue.Queue[str] = queue.Queue()
        threading.Thread(target=lambda: output.put(process.stdout.readline()), daemon=True).start()
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        try:
            line = output.get(timeout=30)
        except queue.Empty:
            stderr = process.stderr.read(500) if process.stderr is not None and process.poll() is not None else ""
            fail(f"Atlas MCP server did not answer initialize within 30s. {stderr}".rstrip())
            return
        if not line:
            stderr = process.stderr.read(500) if process.stderr is not None else ""
            fail(f"Atlas MCP server exited before answering initialize. {stderr}".rstrip())
            return
        payload = json.loads(line)
        server_name = payload.get("result", {}).get("serverInfo", {}).get("name")
        if payload.get("id") == 1 and server_name == "Atlas":
            elapsed = time.monotonic() - started
            pass_(f"Atlas MCP stdio handshake succeeded in {elapsed:.1f}s.")
        else:
            fail(f"Atlas MCP initialize returned an unexpected response: {payload}")
    except Exception as exc:
        fail(f"Atlas MCP stdio handshake failed: {exc}")
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


def check_settings() -> tuple[str | None, str | None, bool]:
    try:
        from app.core.config import get_settings
    except Exception as exc:
        fail(f"Could not import Atlas settings: {exc}")
        return None, None, False

    settings = get_settings()
    pass_(
        "Settings loaded: "
        f"storage={settings.storage_mode}, "
        f"database={redact_database_url(settings.database_url)}, "
        f"api={settings.api_url}, "
        f"auto_start_docker={settings.auto_start_docker}."
    )
    if settings.openai_api_key is None:
        warn("ATLAS_OPENAI_API_KEY is not set; Atlas will use offline deterministic extraction and retrieval.")
    else:
        pass_("ATLAS_OPENAI_API_KEY is set; Atlas can use model-assisted extraction and retrieval.")
    return settings.storage_mode, settings.api_url, settings.auto_start_docker


def check_docker(storage_mode: str | None, auto_start_docker: bool) -> None:
    command = find_docker_command()
    if command is None:
        if storage_mode == "postgres" and auto_start_docker:
            fail("Docker is needed for managed local PostgreSQL but was not found. Set ATLAS_DOCKER_COMMAND or install Docker Desktop.")
        else:
            warn("Docker was not found. This is fine for SQLite or cloud PostgreSQL.")
        return
    pass_(f"Docker command found: {command}")
    if docker_is_ready(command):
        pass_("Docker daemon is reachable.")
    elif storage_mode == "postgres" and auto_start_docker:
        fail("Docker is installed but the daemon is not reachable. Start Docker Desktop, then rerun doctor.")
    else:
        warn("Docker is installed but the daemon is not reachable.")


def check_database() -> None:
    try:
        from sqlalchemy import text

        from app.db import engine
    except Exception as exc:
        fail(f"Could not import database engine: {exc}")
        return

    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
        pass_("Database connection succeeded.")
    except Exception as exc:
        fail(f"Database connection failed: {exc}")
        return

    if engine.dialect.name == "sqlite":
        from app.db import initialize_database

        try:
            initialize_database()
        except Exception as exc:
            fail(f"SQLite schema initialization failed: {exc}")
            return
        pass_("SQLite schema is initialized by the Atlas API startup path.")
        return

    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            cwd=PROJECT_ROOT / "backend",
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        warn(f"Could not check Alembic revision: {exc}")
        return

    revision = result.stdout.strip() or result.stderr.strip()
    if result.returncode == 0 and revision:
        pass_(f"Alembic current revision: {revision}")
    elif result.returncode == 0:
        warn("Alembic returned no current revision.")
    else:
        fail(f"Alembic check failed: {revision}")


def check_api(api_url: str | None) -> None:
    if api_url is None:
        return
    try:
        with urlopen(f"{api_url.rstrip('/')}/api/v1/health", timeout=3) as response:
            if response.status == 200:
                pass_("Atlas API health endpoint is reachable.")
            else:
                fail(f"Atlas API returned HTTP {response.status}.")
    except (HTTPError, URLError, OSError) as exc:
        warn(f"Atlas API is not currently reachable. MCP should start it on demand; if not, check work/atlas-api.log. Detail: {exc}")


def main() -> int:
    print("Atlas doctor")
    print("============")
    check_python()
    check_dependencies()
    check_codex_config()
    check_mcp_handshake()
    storage_mode, api_url, auto_start_docker = check_settings()
    check_docker(storage_mode, auto_start_docker)
    check_database()
    check_api(api_url)
    print("------------")
    if failures:
        print(f"Doctor found {failures} failure(s) and {warnings} warning(s).")
        return 1
    print(f"Doctor found no failures and {warnings} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
