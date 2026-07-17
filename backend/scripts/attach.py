"""Attach the global Atlas install to the current Codex project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


def parse_args(argv: list[str]) -> argparse.Namespace:
    if argv and argv[0].lower() == "attach":
        argv = argv[1:]
    parser = argparse.ArgumentParser(description="Attach this Codex project to the Atlas MCP server.")
    parser.add_argument("target", nargs="?", default=".", help="Project folder to attach. Defaults to the current directory.")
    parser.add_argument("--project-name", "-n", help="Atlas project name. Defaults to the target folder name.")
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
    print(f"Atlas attached {target_root} as project {project_name}.")
    print(f"Codex config: {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
