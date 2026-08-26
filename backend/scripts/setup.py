"""Interactive local setup for Atlas storage.

This deliberately stays a small bootstrap script rather than a full CLI. It
writes only Atlas-owned environment keys and leaves application data untouched.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
CODEX_CONFIG_PATH = PROJECT_ROOT / ".codex" / "config.toml"
DEPENDENCY_MARKER_PATH = PROJECT_ROOT / "work" / ".requirements.sha256"
LOCAL_POSTGRES_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:5434/atlas"
LOCAL_SQLITE_URL = f"sqlite:///{(PROJECT_ROOT / 'work' / 'atlas.db').resolve().as_posix()}"
REQUIRED_MODULES = [
    "alembic",
    "fastapi",
    "mcp",
    "openai",
    "pgvector",
    "psycopg2",
    "pydantic_settings",
    "pytest",
    "sqlalchemy",
    "uvicorn",
]
def validate_runtime() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Atlas requires Python 3.11 or newer. Python 3.13 is recommended.")
    if sys.prefix == sys.base_prefix:
        raise SystemExit(
            "Create and use a project virtual environment before setup, for example: "
            ".venv/bin/python backend/scripts/setup.py"
        )


def _requirements_hash() -> str:
    return hashlib.sha256((PROJECT_ROOT / "requirements.txt").read_bytes()).hexdigest()


def dependencies_are_available() -> bool:
    return all(importlib.util.find_spec(module) is not None for module in REQUIRED_MODULES)


def ensure_codex_work_permissions() -> None:
    """Create the legacy runtime directory for local logs and SQLite state."""
    work_path = PROJECT_ROOT / "work"
    work_path.mkdir(parents=True, exist_ok=True)


def install_dependencies() -> None:
    """Install the declared runtime once, then skip repeat setup runs."""
    requirements_hash = _requirements_hash()
    if dependencies_are_available():
        if DEPENDENCY_MARKER_PATH.exists() and DEPENDENCY_MARKER_PATH.read_text(encoding="utf-8").strip() == requirements_hash:
            print("Atlas dependencies are already installed; skipping pip install.")
            return
        if not DEPENDENCY_MARKER_PATH.exists():
            DEPENDENCY_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
            DEPENDENCY_MARKER_PATH.write_text(requirements_hash + "\n", encoding="utf-8")
            print("Atlas dependencies are already available; recorded the current requirements marker.")
            return

    print("Installing Atlas dependencies into the active Python environment...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(PROJECT_ROOT / "requirements.txt")],
        check=True,
    )
    DEPENDENCY_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEPENDENCY_MARKER_PATH.write_text(requirements_hash + "\n", encoding="utf-8")


def find_docker_command() -> str | None:
    configured = os.environ.get("ATLAS_DOCKER_COMMAND")
    if configured:
        return configured
    return shutil.which("docker")


def docker_is_ready(docker_command: str | None = None) -> bool:
    command = docker_command or find_docker_command()
    if command is None:
        return False
    try:
        return subprocess.run([command, "info"], capture_output=True, timeout=8, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _should_migrate_existing_database() -> bool:
    return input("Apply the Atlas schema to this PostgreSQL database now? [y/N]: ").strip().lower() in {"y", "yes"}


def choose_storage() -> tuple[str, str, bool, bool, bool]:
    docker_command = find_docker_command()
    docker_installed = docker_command is not None
    docker_ready = docker_is_ready(docker_command)
    if docker_installed:
        if docker_ready:
            docker_status = "Docker is installed and reachable."
        else:
            docker_status = "Docker is installed, but its daemon is not reachable yet."
        print(
            f"{docker_status}\n"
            "Atlas storage options:\n"
            "  1) Local PostgreSQL - Atlas starts Docker and migrates it\n"
            "  2) Local PostgreSQL - I will start Docker myself\n"
            "  3) Existing PostgreSQL URL\n"
            "  4) Local SQLite (no Docker, single-machine)"
        )
        choice = input("Choose 1, 2, 3, or 4 [4]: ").strip() or "4"
        if choice == "1":
            return "postgres", LOCAL_POSTGRES_URL, True, True, True
        if choice == "2":
            # The user has already started the same compose database manually.
            # Apply the schema now; if it is still unavailable, the existing
            # PostgreSQL recovery message tells them how to retry safely.
            return "postgres", LOCAL_POSTGRES_URL, False, True, False
        if choice == "3":
            return "postgres", input("PostgreSQL SQLAlchemy URL: ").strip(), False, _should_migrate_existing_database(), False
        if choice == "4":
            return "sqlite", LOCAL_SQLITE_URL, False, False, False
    else:
        print("Docker is not installed or not discoverable. Atlas can use:\n  1) Local SQLite (no Docker, single-machine)\n  2) Existing PostgreSQL URL")
        choice = input("Choose 1 or 2 [1]: ").strip() or "1"
        if choice == "1":
            return "sqlite", LOCAL_SQLITE_URL, False, False, False
        if choice == "2":
            return "postgres", input("PostgreSQL SQLAlchemy URL: ").strip(), False, _should_migrate_existing_database(), False
    raise SystemExit("Invalid storage selection. Run setup again and choose a listed option.")


def write_environment(storage_mode: str, database_url: str, auto_start_docker: bool = False) -> None:
    if not database_url:
        raise SystemExit("A database URL is required for PostgreSQL.")
    existing = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    replacements = {
        "ATLAS_STORAGE_MODE": f"ATLAS_STORAGE_MODE={storage_mode}",
        "ATLAS_DATABASE_URL": f"ATLAS_DATABASE_URL={database_url}",
        "ATLAS_AUTO_START_API": "ATLAS_AUTO_START_API=true",
        "ATLAS_AUTO_START_DOCKER": f"ATLAS_AUTO_START_DOCKER={str(auto_start_docker).lower()}",
        "ATLAS_PROJECT_NAME": f"ATLAS_PROJECT_NAME={PROJECT_ROOT.name}",
    }
    output: list[str] = []
    seen: set[str] = set()
    for line in existing:
        key = line.partition("=")[0]
        if key in replacements:
            output.append(replacements[key])
            seen.add(key)
        else:
            output.append(line)
    output.extend(value for key, value in replacements.items() if key not in seen)
    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _atlas_config_block(python_path: str, project_path: str, project_name: str) -> str:
    install_path = project_path
    server_path = (PROJECT_ROOT / "mcp_server" / "server.py").resolve().as_posix()
    return (
        "[mcp_servers.atlas]\n"
        f'command = "{python_path}"\n'
        f'args = ["{server_path}"]\n'
        f'cwd = "{install_path}"\n'
        "startup_timeout_sec = 180\n"
        "\n"
        "[mcp_servers.atlas.env]\n"
        f'ATLAS_PROJECT_NAME = "{project_name}"\n'
        f'PYTHONPATH = "{install_path}"\n'
    )


def _remove_atlas_blocks(content: str) -> str:
    lines = content.splitlines()
    output: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped in {"[mcp_servers.atlas]", "[mcp_servers.atlas.env]"}:
            skipping = True
            continue
        if skipping and stripped.startswith("[") and stripped.endswith("]"):
            skipping = False
        if not skipping:
            output.append(line)
    return "\n".join(output).rstrip()


def write_codex_config() -> None:
    """Bind this project to the Python environment that ran setup."""
    CODEX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    python_path = Path(sys.executable).resolve().as_posix()
    project_path = PROJECT_ROOT.as_posix()
    project_name = PROJECT_ROOT.name
    try:
        CODEX_CONFIG_PATH.write_text(
            _atlas_config_block(python_path, project_path, project_name),
            encoding="utf-8",
        )
    except PermissionError as exc:
        raise SystemExit(
            "Codex is using .codex/config.toml. Close Codex, rerun setup, then open a fresh Atlas task."
        ) from exc
    # Codex Desktop only loads MCP servers from the user-global config.toml,
    # not from this project-local one, so register Atlas there as well.
    try:
        write_global_codex_config(python_path, project_path, project_name)
    except OSError as exc:
        print(
            "Warning: Atlas registered the project-local MCP server, but could not "
            f"update the global Codex config ({exc}). Codex Desktop may not list the "
            "Atlas MCP server until the global config is updated."
        )


def write_global_codex_config(python_path: str, project_path: str, project_name: str) -> None:
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else (Path.home() / ".codex")
    global_path = base / "config.toml"
    existing = global_path.read_text(encoding="utf-8") if global_path.exists() else ""
    preserved = _remove_atlas_blocks(existing)
    block = _atlas_config_block(python_path, project_path, project_name)
    global_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"{preserved}\n\n{block}" if preserved else block
    global_path.write_text(content.rstrip() + "\n", encoding="utf-8")


def migrate_postgres(start_local_container: bool) -> None:
    if start_local_container:
        docker_command = find_docker_command()
        if docker_command is None:
            raise SystemExit("Docker is not installed or not discoverable. Start its daemon or set ATLAS_DOCKER_COMMAND.")
        subprocess.run([docker_command, "compose", "up", "-d", "db"], cwd=PROJECT_ROOT, check=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=PROJECT_ROOT / "backend", check=True)


def main() -> None:
    validate_runtime()
    ensure_codex_work_permissions()
    try:
        install_dependencies()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Atlas could not install dependencies. Fix the Python or network issue, then rerun setup.\n{exc}") from exc
    storage_mode, database_url, start_local_container, apply_migrations, auto_start_docker = choose_storage()
    write_environment(storage_mode, database_url, auto_start_docker)
    write_codex_config()
    if storage_mode == "postgres" and apply_migrations:
        try:
            migrate_postgres(start_local_container)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            if start_local_container:
                write_environment("sqlite", LOCAL_SQLITE_URL)
                storage_mode = "sqlite"
                print("Atlas could not start local PostgreSQL, so it safely switched to local SQLite. You can rerun setup later.")
                print(f"Details: {exc}")
            else:
                print("Atlas kept your PostgreSQL configuration, but could not apply the schema automatically.")
                print(f"Details: {exc}")
                print("Start the database or correct the URL, then rerun setup and choose the PostgreSQL option again.")
    print(f"Atlas is configured for {storage_mode}. Open a new Codex task in this project; its Atlas MCP server will start the local API automatically.")


if __name__ == "__main__":
    main()
