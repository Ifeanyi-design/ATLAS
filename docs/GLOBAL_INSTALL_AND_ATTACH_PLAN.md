# Atlas Global Install and Attach Plan

## Decision

Atlas should move from "copy Atlas into every project" to "install Atlas once, attach many projects."

The preferred local shape is:

```text
C:\Users\Admin\Atlas
  Atlas code
  .venv
  .env
  work\atlas.db
  dashboard
```

Each Codex project keeps a small project-local `.codex/config.toml` for its name, while `atlas attach` also writes the Atlas server into your global `~/.codex/config.toml` so Codex Desktop can start it.

## Why

Atlas already stores many projects in one database through the `projects` table and `project_id` scoping. The confusing behavior came from the running API deciding the default project from its own `.env`, so a second project could accidentally log to the first project's name when both used `localhost:8000`.

The fix is to make the calling MCP send the desired project name to the API.

## Workflow

One-time install:

```powershell
atlas setup
```

Per-project attach:

```powershell
cd C:\path\to\my-project
atlas attach --project-name bizlive-dashboard
```

The attach command writes:

```toml
[mcp_servers.atlas]
command = "C:/path/to/your/Atlas/.venv/Scripts/python.exe"
args = ["C:/path/to/your/Atlas/mcp_server/server.py"]
cwd = "C:/path/to/your/Atlas"
startup_timeout_sec = 180

[mcp_servers.atlas.env]
"ATLAS_PROJECT_NAME" = "bizlive-dashboard"
"PYTHONPATH" = "C:/path/to/your/Atlas"
```

The paths are whatever install folder you chose. `atlas attach` generates the correct local paths for each machine, so do not copy this block between computers.

## Installer Direction

A future installer should unpack Atlas into a stable folder such as `C:\Users\Admin\Atlas`, create `.venv`, install requirements, run setup, and optionally add the Atlas folder to the user's PATH so `atlas` can be run from any project directory.

The current first installer is `install-atlas.ps1`. A proper EXE installer should wrap that flow with Inno Setup first; MSI/WiX can wait until Atlas needs enterprise deployment behavior.

Run PATH tests from a normal user terminal. Elevated or sandboxed shells can write a different user environment hive, which makes the installer appear to add PATH while ordinary terminals still do not see `atlas`.

## Stop Command

Atlas should provide a manual stop command:

```powershell
atlas stop
```

The command should confirm the configured local API health endpoint identifies as `atlas-api`, then stop the process listening on that port. This is safer than blindly killing anything on port 8000.

Automatic idle shutdown is deferred. It would require request/activity tracking and could surprise a user who leaves the dashboard open.

## Editable Memory (implemented 2026-07-17)

Editable stored memory is a good next feature, but it should be implemented deliberately:

1. The API updates a decision's `decision`, `reason`, and `affected_files` only after verifying its project ID.
2. Every save recomputes that memory's embedding and rebuilds the project running summary from current saved decisions.
3. The dashboard provides an edit/save/cancel form for each decision.
4. The MCP provides `edit_memory(decision_id, decision?, reason?, affected_files?)`. Use `search` first to identify the memory ID; Atlas does not choose a fuzzy match automatically.

Do not edit raw database rows directly from the UI without rebuilding derived state.

## Dashboard

Keep the dashboard web-based. It is easier for Codex, local debugging, and future phone access.

PIN protection is optional through `ATLAS_DASHBOARD_PIN`. Localhost development can leave it unset. LAN mode now exists: set `ATLAS_API_HOST=0.0.0.0` **after** setting `ATLAS_DASHBOARD_PIN`, otherwise the dashboard would be open on the network without protection.
