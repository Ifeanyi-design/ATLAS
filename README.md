# Atlas

> **Atlas prevents AI coding agents from silently reversing your project's engineering decisions across sessions.**

Atlas is a project memory tool for Codex. It saves important engineering decisions, keeps the reasons attached to them, and brings the relevant ones back when a new task starts. If a request goes against an earlier choice, Atlas warns before work begins.

I built it for OpenAI Build Week in the Developer Tools track. It is not a generic chat-memory system or a background transcript recorder. The point is narrower: help Codex remember the engineering intent of a project without replaying whole conversations.

## In One Minute

AI coding agents can start a fresh task without the reasoning behind a project's earlier choices. That makes it easy to repeat debates or accidentally reverse architecture.

Atlas makes the durable context available again:

1. A Codex task records a material decision, its rationale, affected files, and optional UI/design context.
2. A later task retrieves only the relevant decisions and running project summary.
3. If the new request conflicts with prior engineering intent, Atlas returns the original decision and reason before implementation starts.
4. The dashboard provides a searchable, project-scoped audit trail of decisions and conflict overrides.

The result: fresh Codex tasks can stay aligned with the project instead of starting from zero.

For a concise recording flow, see the [Build Week demo script](docs/DEMO_SCRIPT.md).
For product internals, storage behavior, retrieval flow, and self-testing, see the [Atlas product explainer](docs/PRODUCT_EXPLAINER.md).

## Why Atlas Exists

Codex is strongest when it has the right context. The hard part is that engineering context changes shape over time:

- one task decides to use PostgreSQL;
- another task starts fresh and no longer sees that decision;
- a later prompt asks for MongoDB or a conflicting pattern;
- the agent can confidently implement the wrong thing because the prior decision is missing.

Atlas solves this by storing decisions as structured project memory. A new Codex task can ask Atlas for relevant context before work begins, search memory during work, and log important decisions after work. If the new prompt conflicts with prior memory, Atlas returns the original decision and reason before the mistake becomes code.

## Core Features

- MCP server for Codex with `get_context`, `log_decision`, `search`, `edit_memory`, `remove_memory`, and `override_conflict`.
- Project-scoped memory backed by SQLite, local Docker PostgreSQL, or an existing PostgreSQL database.
- PostgreSQL + pgvector support for realistic shared/team retrieval.
- Offline deterministic mode when no OpenAI API key is configured.
- Optional OpenAI API mode for richer extraction, embeddings, summaries, curation, and conflict checks.
- Fresh-session mode that injects no prior memory but still permits new decisions to be logged.
- Structured UI/design context capture and direct injection for UI-related tasks.
- One-page dashboard for decisions, conflicts, design context, storage state, and estimated context avoided.
- Doctor command for setup/debug checks before changing storage.
- Attach command for using one Atlas install across many Codex projects.
- Optional dashboard/API PIN for local-network-ready deployments.

## Architecture

```text
Codex task
   |
   | MCP tools
   v
Atlas MCP server
   |
   | starts local API on demand
   v
FastAPI service
   |
   +-- SQLite for simplest local demo
   +-- PostgreSQL + pgvector for shared or production-like memory
```

Codex starts the Atlas MCP server from the project-local `.codex/config.toml`. The MCP server starts the local FastAPI service only when a tool call needs it. The database stores projects, sessions, decisions, embeddings, structured design context, and conflict events.

Atlas is intentionally not a background transcript recorder. It stores only material engineering decisions that pass extraction and validation.

## Quick Start for Judges

### Preferred Windows path: installer

Download `AtlasSetup.exe` from the project's GitHub Release, run it, select **Add Atlas to my user PATH**, and select **Run Atlas setup now** on the final installer page.

When setup opens, choose **SQLite**. Then create or open a small project folder and attach it:

```powershell
mkdir C:\AtlasJudgeDemo
cd C:\AtlasJudgeDemo
atlas attach . --project-name atlas-judge-demo
```

Open a **fresh Codex task** in `C:\AtlasJudgeDemo`, run `/mcp` to confirm `atlas` is enabled, then ask Codex to use Atlas before changing architecture. The first Atlas tool call starts the local API. Open `http://127.0.0.1:8000/dashboard/` to view saved memory.

### Source fallback

This is the self-contained Windows path for judges who choose to run from source. It needs no Docker, cloud database, Node frontend, or OpenAI API key.

1. Clone the repository and open PowerShell in its root folder.
2. Create the Python environment and run setup:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\python.exe backend\scripts\setup.py
   ```

3. Choose **SQLite** when asked. Setup installs dependencies and writes the local `.env` plus `.codex/config.toml`.
4. Check the installation:

   ```powershell
   .\.venv\Scripts\python.exe backend\scripts\doctor.py
   .\.venv\Scripts\python.exe -m pytest backend\tests -q
   ```

5. Open a **fresh Codex task** in the repository folder and run `/mcp`; `atlas` should be enabled.
6. Ask Codex to use Atlas before changing architecture. The first Atlas tool call starts the local API automatically.
7. Open `http://127.0.0.1:8000/dashboard/` after that first tool call to view the timeline, conflict evidence, design context, and editable saved memory.

To test the full loop, log a `Decision:` plus `Reason:`, start a fresh task and retrieve context, request a contradictory change, then open the dashboard. See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for exact demo text.

## Storage Options

| Mode | Best for | Strengths | Limits |
| --- | --- | --- | --- |
| SQLite | Fastest judge/demo path | No Docker, no network, single local file | Local JSON embedding ranking instead of pgvector indexes |
| Local Docker PostgreSQL | Realistic local development | PostgreSQL, pgvector, migrations, durable Docker volume | Docker Desktop must be installed and running |
| Existing/cloud PostgreSQL | Build Week demo reliability and sharing | Durable outside the laptop, no local Docker dependency, production-like retrieval | Needs database URL and network access |

For a live Build Week demo, cloud PostgreSQL is the strongest story if the database is already stable. SQLite is the safest emergency fallback.

## Setup in Detail

1. Create and activate a virtual environment.

   ```powershell
   py -m venv .venv
   ```

2. Run setup.

   ```powershell
   .venv\Scripts\python.exe backend\scripts\setup.py
   ```

3. Choose storage:

   - Local Docker PostgreSQL managed by Atlas.
   - Local Docker PostgreSQL started manually.
   - Existing PostgreSQL URL.
   - Local SQLite.

4. Setup writes:

   - `.env` with Atlas settings.
   - `.codex/config.toml` with the MCP command Codex should run.
   - `work/.requirements.sha256` so repeated setup runs can skip dependency reinstall when requirements have not changed.

5. Open a fresh Codex task from this project folder. If Codex was already open before setup, close that task and start a new one.

## Doctor Check

When Atlas feels broken, run:

```powershell
.venv\Scripts\python.exe backend\scripts\doctor.py
```

The doctor checks:

- supported Python version;
- active virtual environment;
- dependency imports;
- `.codex/config.toml`;
- selected storage settings;
- Docker command and daemon where relevant;
- database connectivity;
- SQLite schema initialization or PostgreSQL Alembic migration revision;
- local API health.

It is normal for the API health check to warn when no Atlas MCP process is currently running. Atlas starts the API on demand.

## Daily Use

After setup, daily use is simple:

1. Start Docker Desktop only if using Docker PostgreSQL.
2. Open Codex in this project folder.
3. Open a fresh task.
4. Confirm `/mcp` lists `atlas`.
5. Use Atlas tools as part of the Codex workflow.

The MCP process is owned by the Codex task. The local API may remain alive on the configured port until it is stopped, the task exits cleanly, or the machine shuts down. Use `atlas stop` when you want to free the port or force a clean API restart. Memory remains in SQLite, the Docker PostgreSQL volume, or the configured cloud database.

## Making Codex Use Atlas Consistently

After `atlas attach`, Codex can see the Atlas MCP tools in fresh tasks, but v1 is still an explicit MCP workflow rather than a background watcher. To make tool use consistent, `atlas attach` also creates or updates the attached project's active Codex instruction file:

- If `AGENTS.override.md` already exists in the target folder, Atlas updates that file because Codex gives it priority.
- Otherwise Atlas creates or updates `AGENTS.md`.
- Existing user instructions are preserved. Atlas only manages the block between `ATLAS-CODEX-INSTRUCTIONS:START` and `ATLAS-CODEX-INSTRUCTIONS:END`.
- Use `atlas attach --no-agents ...` if you only want the MCP config and prefer to manage instructions yourself.

The Atlas block says:

```markdown
Before making architecture, storage, API, data-model, or UI-pattern changes, call Atlas `get_context` with the user's request.
During work, use Atlas `search` when prior project decisions may matter.
After a material engineering decision is made, call Atlas `log_decision` with the decision, reason, and affected files.
If Atlas reports a conflict and the user chooses to continue, call `override_conflict` with the reason.
Use `edit_memory` or `remove_memory` only when the user explicitly asks to correct or delete saved Atlas memory.
```

Start a fresh Codex task after changing these files. Codex reads project instructions when the session starts, so an already-open task may not see the new guidance.

## MCP Tool Contract

`get_context(prompt, fresh_session=false)`

Retrieves project-scoped memory for a new task. It returns the running summary, relevant decisions, direct UI/design JSON when appropriate, and any conflict warning. When `fresh_session=true`, Atlas returns no injected memory but does not disable future decision logging.

`log_decision(exchange)`

Extracts and stores a material engineering decision, its reason, affected files, embedding, optional structured design context, and the updated running summary. If the exchange contains no real decision, Atlas stores nothing.

`search(query, limit=10)`

Performs explicit mid-task recall against project-scoped decisions.

`remove_memory(...)`

Removes one decision, a list of decisions, a UTC date range, or all project memory. Whole-project deletion requires the exact confirmation phrase `DELETE ALL PROJECT MEMORY`.

`edit_memory(decision_id, decision?, reason?, affected_files?)`

Edits one known saved memory. Use `search(...)` first when you need its decision ID. Atlas recomputes the memory embedding and rebuilds that project's running summary after every edit.

`override_conflict(conflict_event_id, reason)`

Records a deliberate, auditable exception when a developer chooses to continue despite a conflict warning.

## Example Decision Capture

Offline deterministic mode works best with explicit decision markers:

```text
Decision: Use PostgreSQL with pgvector for Atlas memory.
Reason: It keeps decisions project-scoped and supports local vector retrieval.
Affected file: backend/app/db.py
```

For UI work, include structured design context:

```text
Decision: Use compact dashboard tabs for Atlas memory review.
Reason: Judges need to scan decisions, conflicts, design evidence, and system state quickly.
Design context: {"colors":{"accent":"#38d9a9"},"spacing":{"card":12},"components":["tabs","timeline","conflict panel"]}
Affected file: dashboard/app.js
```

With `ATLAS_OPENAI_API_KEY`, Atlas can extract decisions from more natural exchanges and use semantic embeddings/model-assisted curation.

## Dashboard

After Atlas starts the local API, open:

[http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)

The dashboard shows:

- project selection;
- newest-first decision timeline;
- an edit-and-save form for each decision (including reason and affected files);
- conflict events and override reasons;
- stored design-context records;
- active storage and intelligence mode;
- estimated context avoided.

The context numbers are estimates, not billing claims. Atlas estimates how much context payload was avoided compared with carrying a larger long-session history forward. It does not claim to measure provider cache hits, invisible reasoning tokens, or final invoice savings.

## Project Isolation and Privacy

Every decision, context lookup, search, design-context lookup, deletion, and conflict event is filtered by `project_id`.

The default project is created from the configured project name. If multiple workspaces share one database, set a unique `ATLAS_PROJECT_NAME` in each `.env` before the first Atlas call. Passing a specific `project_id` is an advanced/manual action.

Global memory and linked-project memory are intentionally deferred to v2.

### Shared cloud memory for a team

Teams can share one project's Atlas memory today by using the same cloud PostgreSQL database URL and the same `--project-name` on every member's machine. Each teammate installs Atlas locally, chooses **Existing PostgreSQL URL** during `atlas setup`, then runs:

```powershell
cd C:\path\to\the\team-project
atlas attach . --project-name bizlive-dashboard
```

Do not copy another teammate's `.codex/config.toml`; it contains an absolute path to that person's Atlas installation. `atlas attach` generates the correct local config for each person. The shared project name resolves to the same project ID in the common database. Atlas v1 assumes a trusted team and does not yet provide per-user roles or project permissions.

### Docker port and ownership

Atlas's supplied local Docker database is named `atlas-db` in Docker Desktop. It maps **host port 5434** to PostgreSQL's internal port **5432**. Option 1 in setup manages `docker compose up -d --wait db` on Atlas use; Docker Desktop must still be installed and running. Option 2 expects the user to run `docker compose up -d db` from the Atlas install folder first, then Atlas applies its schema but does not automatically restart Docker later.

## Global Install and Project Attach

The preferred local workflow is one Atlas install shared by many Codex projects. Atlas keeps one database in the install folder and separates project memory by `project_id`.

Install Atlas into a stable folder:

```powershell
.\install-atlas.ps1 -InstallDir "$env:USERPROFILE\Atlas"
cd "$env:USERPROFILE\Atlas"
.\atlas setup
```

The installer copies program files, creates `.venv`, prepares the install-level `work` folder for Codex sandbox writes, and can add the Atlas folder to your user PATH. Setup still chooses storage and writes the install-level `.env`. SQLite storage is anchored to the install folder, so attached projects do not create their own Atlas databases.

Attach any Codex project:

```powershell
atlas attach C:\path\to\my-project --project-name my-project
```

If Atlas is not on PATH, use the full command:

```powershell
C:\Users\Admin\Atlas\atlas attach C:\path\to\my-project --project-name my-project
```

`atlas attach` writes that project's `.codex/config.toml` with the shared Atlas MCP command and `[mcp_servers.atlas.env] ATLAS_PROJECT_NAME`. The MCP sends that project name to the API, so one running Atlas API can serve multiple projects without logging them all under the install folder name.

The older copy-or-clone-per-project workflow still works, but it is no longer the easiest path.

## Runtime Commands

```powershell
atlas setup
atlas attach C:\path\to\project --project-name project-name
atlas doctor
atlas stop
```

`atlas stop` stops the local Atlas API listening on the configured `ATLAS_API_URL` port after confirming the health endpoint identifies as `atlas-api`. It is useful when you want to free port `8000` or force a fresh API start. Atlas does not currently auto-shut down after idle time; that is a possible later feature.

## Dashboard PIN

For localhost-only use, no PIN is required. Before exposing the dashboard on your local network, set:

```env
ATLAS_DASHBOARD_PIN=123456
```

When a PIN is configured, non-health API routes require the `X-Atlas-Dashboard-Pin` header and the dashboard prompts for the PIN before loading memory.

## Supported Platforms

Atlas is a local developer tool. The supported Build Week judge path is Windows 10/11 x64 with PowerShell and Codex Desktop. The architecture is intentionally portable to macOS and Linux because the backend is Python/FastAPI, the storage choices are SQLite or PostgreSQL, and the MCP server is launched through a project-local command, but those platforms are not the primary packaged/demo path for this submission.

Platform notes:

- Windows 10/11 x64: primary tested and supported Build Week platform.
- Codex Desktop: required for the project-local MCP workflow.
- PowerShell: used by the Windows installer and setup commands.
- Python 3.11 or newer: required for source setup; the installer creates Atlas's `.venv` from an installed Python.
- macOS/Linux: expected to work with Python 3.11+, but not packaged or fully tested for the Build Week judge path.
- Docker Desktop: optional, only needed for local Docker PostgreSQL.
- OpenAI API key: optional. Atlas runs without it in deterministic offline mode.

## Judge Test Path Without Rebuilding

Judges do not need to rebuild a frontend or run a separate Node process. The dashboard is static JavaScript served by FastAPI. Follow **Quick Start for Judges** above, choose SQLite, and use the demo script. This tests the full product loop without Docker, cloud credentials, or an OpenAI API key.

## Repository URL

Submission repository:

[https://github.com/Ifeanyi-design/ATLAS](https://github.com/Ifeanyi-design/ATLAS)

If the repository is public, include a license file. If it is private, Devpost requires sharing access with the event addresses listed in the submission form.

## Codex Collaboration

Atlas was built primarily through Codex collaboration during OpenAI Build Week, using GPT-5.6 model sessions for the main implementation work and later Codex sessions for reliability, documentation, and submission polish.

Codex accelerated the work in several places:

- Project planning: turning the initial product idea into a scoped v1 brief, phase plan, and demo spine.
- Backend implementation: building the FastAPI service, SQLAlchemy models, migrations, storage selection, and API routes.
- MCP integration: exposing Atlas as Codex tools through `log_decision`, `get_context`, `search`, `edit_memory`, `remove_memory`, and `override_conflict`.
- Retrieval and memory behavior: implementing project-scoped recall, fresh-session behavior, structured design-context capture, and conflict detection.
- Dashboard work: creating a dependency-free dashboard for decisions, conflicts, design context, storage state, and estimated context avoided.
- Reliability: adding setup recovery, doctor checks, Docker detection, cloud PostgreSQL support, SQLite fallback, and MCP startup fixes.
- Verification: writing and running focused tests across backend behavior, MCP contracts, storage modes, and restart scenarios.

Key human product decisions:

- Keep Atlas project-scoped by `project_id`, with one local install able to attach many Codex projects.
- Store decisions and reasons, not full transcripts.
- Treat conflicts as warnings with auditable overrides, not silent hard blocks.
- Support SQLite for frictionless testing and PostgreSQL + pgvector for production-like retrieval.
- Keep context-savings claims honest by showing estimates rather than claiming measured billing reductions.

GPT-5.6 and Codex contributed most directly to implementation speed, architecture iteration, bug diagnosis, test creation, and documentation. The final submission positioning is intentionally honest: Atlas is an MCP-enforced architectural memory and conflict-warning layer for Codex, not a universal background memory service.

The required Codex `/feedback` session ID is submitted in the Devpost form rather than committed into the public repository.

## Why Not Just a Markdown File?

Atlas is meant to work alongside `AGENTS.md`, `CLAUDE.md`, and project notes, not replace them. Markdown files are still the right place for stable rules, setup instructions, coding conventions, and durable architecture notes.

The problem Atlas focuses on is the part that is easy to forget: decisions made during active development, the reason they were made, and later requests that contradict them. A markdown file only helps if a developer remembers to update it and if the next task reads the right section. Atlas stores material decisions as structured project memory, retrieves only the decisions relevant to the current request, and can warn when a new request conflicts with a prior choice.

In short: markdown is passive documentation; Atlas is an active decision layer for Codex.

## Windows PATH Troubleshooting

If `atlas` is not recognized after installing, open a new PowerShell or Command Prompt first. Windows does not refresh PATH inside terminals that were already open before the installer updated the user environment.

If a new terminal still cannot find it, run the command by full path:

```powershell
C:\Users\Admin\Atlas\atlas.cmd attach . --project-name atlas-judge-demo
```

For a custom install folder, replace `C:\Users\Admin\Atlas` with the folder chosen in the installer. After PATH refreshes, the shorter command works:

```powershell
atlas attach . --project-name atlas-judge-demo
```

## Build Week Notes

Atlas is submitted to the OpenAI Build Week Developer Tools track. The core thesis is that long-running agentic development needs durable project decisions, scoped retrieval, and pre-work conflict warnings.

The repository documents:

- the build plan in [docs/PLAN.md](docs/PLAN.md);
- progress history in [docs/PROGRESS.md](docs/PROGRESS.md);
- the product brief in [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md);
- the plain-English runbook in [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Five-Minute Local Demo

1. Log a PostgreSQL architectural decision with `log_decision`.
2. Start a different Codex task and call `get_context` with a related prompt.
3. Ask to replace PostgreSQL with MongoDB; show the conflict and prior reason.
4. Call `search("PostgreSQL")` for explicit recall.
5. Log a UI decision with `Design context: {...}` and show design-context injection.
6. Call `get_context(..., fresh_session=true)` and show no injected decisions.
7. Open the dashboard and show timeline, conflict, design context, storage state, and estimated context avoided.

For the polished Build Week recording, use the three-minute flow above: decision capture, fresh-task recall, conflict warning, search, fresh-session mode, and dashboard evidence.

## Repository Map

- `backend/` - FastAPI service, SQLAlchemy models, migrations, services, scripts, and tests.
- `mcp_server/` - Atlas MCP tool server.
- `dashboard/` - dependency-free dashboard served by FastAPI.
- `docs/` - product brief, implementation plan, runbook, and progress log.
- `infra/` - local PostgreSQL/pgvector provisioning.

## License

This project is intended to be published with the repository license file included. Devpost allows public repositories when they include relevant licensing, or private repositories shared with the required event addresses.
