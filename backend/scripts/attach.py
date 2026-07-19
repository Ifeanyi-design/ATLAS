"""Attach the global Atlas install to the current Codex project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ATLAS_AGENTS_START = "<!-- ATLAS-CODEX-INSTRUCTIONS:START -->"
ATLAS_AGENTS_END = "<!-- ATLAS-CODEX-INSTRUCTIONS:END -->"
ATLAS_AGENTS_BLOCK = f"""{ATLAS_AGENTS_START}
## Atlas Memory Workflow

- Before making architecture, storage, API, data-model, or UI-pattern changes, call Atlas `get_context` with the user's request.
- During work, use Atlas `search` when prior project decisions may matter.
- After a material engineering decision is made, call Atlas `log_decision` with the decision, reason, and affected files.
- If Atlas reports a conflict and the user chooses to continue, call Atlas `override_conflict` with the reason.
- Use Atlas `edit_memory` or `remove_memory` only when the user explicitly asks to correct or delete saved Atlas memory.
{ATLAS_AGENTS_END}
"""


def _toml_string(value: str) -> str:
    return json.dumps(value)


def render_atlas_config(project_name: str) -> str:
    python_path = (PROJECT_ROOT / ".venv" / "Scripts" / "python.exe").resolve().as_posix()
    install_path = PROJECT_ROOT.resolve().as_posix()
    return (
        "[mcp_servers.atlas]\n"
        f"command = {_toml_string(python_path)}\n"
        'args = ["-m", "mcp_server.server"]\n'
        f"cwd = {_toml_string(install_path)}\n"
        "\n"
        "[mcp_servers.atlas.env]\n"
        f"ATLAS_PROJECT_NAME = {_toml_string(project_name)}\n"
    )


def remove_existing_atlas_blocks(content: str) -> str:
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


def write_project_config(target_root: Path, project_name: str) -> Path:
    config_path = target_root / ".codex" / "config.toml"
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    preserved = remove_existing_atlas_blocks(existing)
    atlas_block = render_atlas_config(project_name)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"{preserved}\n\n{atlas_block}" if preserved else atlas_block
    config_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return config_path


def active_agents_path(target_root: Path) -> Path:
    override_path = target_root / "AGENTS.override.md"
    if override_path.exists():
        return override_path
    return target_root / "AGENTS.md"


def upsert_agents_guidance(target_root: Path) -> Path:
    agents_path = active_agents_path(target_root)
    existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    if ATLAS_AGENTS_START in existing and ATLAS_AGENTS_END in existing:
        before, rest = existing.split(ATLAS_AGENTS_START, 1)
        _, after = rest.split(ATLAS_AGENTS_END, 1)
        content = before.rstrip() + "\n\n" + ATLAS_AGENTS_BLOCK + after.lstrip()
    elif existing.strip():
        content = existing.rstrip() + "\n\n" + ATLAS_AGENTS_BLOCK
    else:
        content = f"# {agents_path.name}\n\n" + ATLAS_AGENTS_BLOCK
    agents_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return agents_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    if argv and argv[0].lower() == "attach":
        argv = argv[1:]
    parser = argparse.ArgumentParser(description="Attach this Codex project to the Atlas MCP server.")
    parser.add_argument("target", nargs="?", default=".", help="Project folder to attach. Defaults to the current directory.")
    parser.add_argument("--project-name", "-n", help="Atlas project name. Defaults to the target folder name.")
    parser.add_argument("--no-agents", action="store_true", help="Do not create or update AGENTS.md guidance for Atlas.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    target_root = Path(args.target).resolve()
    if not target_root.exists() or not target_root.is_dir():
        raise SystemExit(f"Atlas attach target is not a folder: {target_root}")
    project_name = (args.project_name or target_root.name).strip()
    if not project_name:
        raise SystemExit("Atlas project name cannot be empty.")
    config_path = write_project_config(target_root, project_name)
    agents_path = None if args.no_agents else upsert_agents_guidance(target_root)
    print(f"Atlas attached {target_root} as project {project_name}.")
    print(f"Codex config: {config_path}")
    if agents_path is not None:
        print(f"Codex instructions: {agents_path}")
        print("Open a fresh Codex task so the updated instructions and MCP config are loaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
