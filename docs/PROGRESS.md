# Atlas Progress Log

Keep entries short. Update `PLAN.md` checkboxes as work is completed.

## 2026-07-15 — Planning locked

- Created the v1 implementation plan and durable project brief.
- Clarified the retrieval contract: vector top-K produces 15–20 candidates; a small model curates a bounded subset. The running project summary remains a separate, incrementally maintained artifact.
- Promoted structured UI/design context into the required demo spine.
- Clarified the architecture and MCP lifecycle: Codex calls `get_context` before work, may call `search` during work, and calls `log_decision` after recognizing a material decision. Atlas remains deliberately non-background for v1.
- Added the North Star principle: reduce cognitive load; do not impose manual maintenance.
- Scaffolded Phase 0: FastAPI health route, PostgreSQL/pgvector Docker setup, SQLAlchemy models, initial Alembic migration, MCP stub tools, seed script, and smoke-test files.
- Verified Python syntax with `python -m compileall -q backend mcp_server`. Runtime migration, test execution, and Codex MCP enumeration remain pending local dependency installation and database startup.
- Next: install dependencies, start the database, migrate, run tests, and register/enumerate the MCP server.

## 2026-07-15 — Local database port correction

- Confirmed the Atlas container accepts the configured `atlas` credentials over its internal TCP connection.
- Host port 5432 did not route those credentials to Atlas. Port 5433 is used by another local project, so Atlas will use host port 5434 while retaining container port 5432.
- Updated runtime configuration to load the project-root `.env` from any working directory.
- Next: recreate the database container, validate host connection on 5434, then run the initial migration.

## 2026-07-15 — Foundation validation

- Recreated the Atlas database container on host port 5434 without removing its volume; verified the host connection as `atlas`.
- Applied the initial Alembic migration successfully.
- Added a pytest import-path configuration for the backend and MCP server; the Phase 0 test suite passes (2 tests).
- Next: seed demo data, start the FastAPI and MCP services, then verify MCP tool enumeration in Codex.

## 2026-07-15 — Session handoff and MCP registration

- Seed data was created and the FastAPI service is running locally at `http://127.0.0.1:8000`.
- The stdio MCP server must be launched by Codex, not kept open in a separate terminal.
- The Codex desktop app has no `codex` CLI command on this machine. Create project-local `.codex/config.toml` with the Atlas server command, then start a new Codex session to enumerate its tools.
- Model guide recorded in `PLAN.md`: GPT-5.5 High for Phase 1 contract design; GPT-5.6 Terra Medium/High for implementation and debugging. “GPT-5.6 Sol” is not available in this Codex app.
- Next: verify `log_decision`, `get_context`, and `search` appear in a new session, then begin Phase 1.

## 2026-07-15 - Phase 1 extraction schema started

- Verified project-local `.codex/config.toml` points Codex at the Atlas MCP server command, but this running session still did not expose the Atlas product tools through tool discovery.
- Began Phase 1 with the strict extraction schema, extraction prompt, JSON validation, and retry behavior.
- Added focused tests for real decisions, no-decision exchanges, malformed output, file-path normalization, and structured design context extraction.
- Verified `pytest backend/tests -q` passes: 8 tests. Non-blocking warnings remain for Starlette TestClient deprecation and pytest cache writes in this checkout.
- Next: implement `log_decision(project_id, session_id, exchange)` persistence, embedding generation, design-context storage, and summary updates.

## 2026-07-15 - Phase 1 decision capture completed

- Implemented the MCP-to-FastAPI `log_decision` path and a project-scoped capture service.
- Accepted decisions now persist the decision, embedding, optional structured design context plus affected file paths, and an incrementally updated project summary in one transaction. Non-decisions create no records.
- Added project/session isolation checks before model calls and focused tests for persistence, no-decision handling, and cross-project session rejection. The backend test suite passes: 11 tests.
- Added the OpenAI SDK dependency. This sandbox could not install it because outbound PyPI access is blocked, so live calls require `pip install -r requirements.txt` in a network-enabled local environment and `ATLAS_OPENAI_API_KEY`.
- Next: begin Phase 2 retrieval and context injection after verifying the MCP tools enumerate in a new Codex session.

## 2026-07-15 - Phase 2 retrieval and offline-first context injection completed

- Implemented `get_context` through the MCP server and FastAPI API with project/session isolation, pgvector top-20 candidate retrieval, bounded curation, and a separate running-summary response field.
- Added direct matching design-context JSON for UI prompts and fresh-session mode, which returns no injected memory while preserving later decision logging.
- Replaced the no-key disabled behavior with a deterministic local fallback: explicit `Decision:`/`Reason:` capture, hashed local embeddings, incremental summary, and lexical curation. An `ATLAS_OPENAI_API_KEY` upgrades to the existing OpenAI extraction, semantic embedding, summary, and curation path.
- Verified `python -m pytest backend/tests -q`: 15 passed. The only warnings are existing Starlette TestClient deprecation and pytest cache permission warnings.
- Next: verify Atlas MCP tool enumeration in a new Codex task, then begin Phase 3 conflict detection and explicit search.

## 2026-07-15 - Phase 3 conflict detection and recall completed

- Implemented the `get_context` conflict contract and persisted detected conflicts to `conflict_events` before context is returned.
- Added explicit `search(project_id, query, limit)` through FastAPI and the Atlas MCP server, using project-scoped pgvector retrieval.
- Offline mode flags only clear reversals of an existing decision; API mode asks the configured small model to check retrieved candidates and falls back locally if that call fails.
- Verified `python -m pytest backend/tests -q`: 19 passed. Existing warnings remain limited to Starlette TestClient deprecation and pytest cache permissions.
- Next: verify Atlas MCP tool enumeration in a new Codex task, then begin the Phase 4 dashboard.

## 2026-07-16 - Local-first storage and developer-controlled conflict handling

- Added an interactive setup path that detects Docker and offers local PostgreSQL, a supplied PostgreSQL URL, or local SQLite. SQLite stores embeddings as JSON and ranks them deterministically in-process; PostgreSQL retains pgvector/HNSW for shared/team use.
- Made the MCP process start the local FastAPI service when it is absent, so ordinary Codex use no longer requires a second API terminal. Startup failures are recorded in `work/atlas-api.log`.
- Removed opaque-ID friction: the MCP server now creates its project on first use and maintains a session automatically, while retaining optional IDs for deliberate cross-project work.
- Made new-user MCP registration portable: setup writes `.codex/config.toml` with that user’s virtual-environment Python path and project root instead of reusing this machine’s path.
- Conflicts remain warnings. They now expose an event ID and can be overridden only with an explicit reason, retained alongside the conflict event for dashboard/audit use.
- Added SQLite storage, automatic project bootstrap, override, and existing behavior coverage. `pytest backend/tests -q` passes: 22 tests.
- Next: verify the updated four-tool MCP enumeration in a fresh Codex task, then build the one-page dashboard with storage mode and override status visible.

## 2026-07-16 - Phase 4 dashboard completed

- Built a dependency-free dashboard served by FastAPI at `/dashboard/`; it needs no Node process or frontend installation.
- Added project selection, optional date filters, newest-first decision timeline, conflict and override evidence, storage/intelligence state, structured design JSON, and loading/empty/error handling.
- Context-savings cards are explicitly estimated from serialized character counts; they do not claim provider cache hits, output-token savings, or invisible model reasoning savings.
- Extended setup to offer managed or manual local Docker PostgreSQL, a supplied PostgreSQL URL, and SQLite. Automatic local PostgreSQL startup now falls back safely to SQLite with a clear recovery message instead of crashing.
- Verified `python -m pytest backend/tests -q`: 24 passed. Next: enumerate the updated MCP tools in a fresh Codex task and run the Phase 5 demo spine end to end.

## 2026-07-16 - Phase 4 verification completed

- Verified the dashboard’s live conflict panel is backed by `conflict_events`, including status and override evidence.
- Updated the system-state display to show the active storage mode together with the SQLite local-ranking limitation or PostgreSQL retrieval detail.
- `pytest` is declared in `requirements.txt`, but this environment does not have it installed and outbound package download is blocked by its network policy. Run `python -m pip install -r requirements.txt` in a network-enabled environment before the Phase 5 test pass.
- Next: run the Phase 5 demo spine end to end against a clean local database.

## 2026-07-16 - Phase 5 validation unblocked

- Used the project `.venv` to run `python -m pytest backend/tests -q`: 24 passed. Existing warnings remain limited to the Starlette TestClient deprecation and unavailable pytest-cache writes.
- Updated the health endpoint test to assert the active configured storage and intelligence modes instead of assuming SQLite, so the suite works with the project’s PostgreSQL configuration.
- Next: run the required Phase 5 demo spine against a clean local database.

## 2026-07-16 - Phase 5 demo spine completed

- Added explicit offline `Design context: { ... }` JSON capture so the no-key demo path persists structured UI context with its decision; coverage brings the backend suite to 25 passing tests.
- Ran the full spine against an isolated clean SQLite database without altering the existing PostgreSQL project memory: logged an architecture decision, retrieved it in a separate session, caught a PostgreSQL-to-MongoDB conflict, searched memory, directly injected one UI context, verified fresh-session zero injection followed by decision capture, and verified dashboard evidence.
- Dashboard evidence: 3 decisions, 1 conflict, 1 structured design-context entry, and transparent context-token estimates. The isolated SQLite storage state correctly states its in-process JSON-embedding ranking limitation.
- Next: Phase 5 polish, documentation, install-path exercise, demo recording, feedback capture, and submission preparation.

## 2026-07-16 - Phase 5 restart and memory guidance

- Made the MCP tools call local-service recovery on every invocation, so a restarted or stopped local API is started again when Atlas is used.
- Setup option 1 now records managed Docker startup explicitly. On a later MCP startup, Atlas restores the local PostgreSQL container before starting the API; manual Docker and supplied/cloud PostgreSQL choices remain non-automatic.
- Added coverage for managed Docker restart behavior. `python -m pytest backend/tests -q` through `.venv` passes: 26 tests.
- Expanded `README.md` with restart and storage behavior, offline structured-context capture, honest token-cost limits, project-scoping assumptions, tool contracts, and a five-minute demo script.
- Next: exercise the installation matrix, finish presentation polish, record the demo, capture feedback, and prepare submission.

## 2026-07-16 - Phase 5 install-path verification

- Verified the SQLite path end to end with an isolated clean database. Docker Compose is installed on this machine, but this session cannot access the Docker daemon; automatic/manual Docker and supplied cloud PostgreSQL still require verification in an environment with those services available.
- Prepared the repository for publishing: runtime databases, logs, `.env`, the virtual environment, and local Codex configuration remain excluded from version control.

## 2026-07-16 - Phase 5 first-run and memory-management polish

- Setup now verifies Python 3.11+, requires a virtual environment, and installs the declared dependencies into that active environment before choosing storage.
- Added project-scoped permanent removal through both the dashboard and the MCP `remove_memory` tool. It supports one decision, an ID list, a complete UTC time range, or the entire project only after an exact confirmation. Removal clears directly derived UI context and conflict evidence, then rebuilds the running summary from remaining memory.
- Dashboard memory review now exposes every captured design-context record, total versus filtered decision counts, UTC date-and-time filters, and explicit confirmations for individual, range, and whole-project deletion.
- Expanded README recovery guidance for sleep, shutdown, crashes, Docker, SQLite, and cloud storage. Final test count is recorded after the Phase 5 verification pass.

## 2026-07-16 - Phase 5 setup reliability and Build Week readiness

- Split Docker detection into "installed" and "daemon reachable" states. Setup now still shows Docker PostgreSQL choices when Docker Desktop is installed but not currently reachable, and it checks the standard Windows Docker Desktop path plus optional `ATLAS_DOCKER_COMMAND`.
- Setup now records a requirements hash marker and skips repeated dependency installation when the active virtual environment already satisfies Atlas imports.
- Added `backend/scripts/doctor.py` to check Python, dependencies, project-local MCP config, settings, Docker, database connectivity, Alembic revision, and API health before changing storage.
- Expanded README guidance on doctor checks, storage tradeoffs, cross-project use, API-key behavior, SQLite limits, and the Build Week recommendation: keep v1 project-scoped, use SQLite for the quickest demo or cloud/PostgreSQL for the most reliable persistent story.

## 2026-07-16 - Phase 5 dashboard run-flow polish

- Added dashboard tabs for Overview, Timeline, Conflicts, Design, and System so the demo has a clearer narrative without a full redesign.
- Added a System run-flow panel that explains the startup chain: storage dependency first, Codex starts the Atlas MCP server from project config, the MCP server starts the local API on demand, and the tools use project memory.
- Expanded the plain-English runbook with separate first-time setup versus daily-use flows for SQLite, cloud PostgreSQL, and Docker PostgreSQL, plus a clearer cross-project explanation.
- Verified `python -m compileall -q backend mcp_server` and `.venv\Scripts\python.exe -m pytest backend\tests -q`: 31 passed. `node --check dashboard/app.js` is blocked in this sandbox by a Windows permission error while Node resolves under `C:\Users\Admin`.

## 2026-07-16 - MCP startup and discovery fix

- Fixed Atlas MCP startup so Codex can enumerate tools without eagerly starting the local API. The API now starts only on tool invocation, gets a longer startup window for slow cloud PostgreSQL paths, and does not inherit the MCP server's stdin handle.
- Verified MCP protocol enumeration returns `log_decision`, `get_context`, `search`, `remove_memory`, and `override_conflict`.
- Created the missing PostgreSQL project row for `258f905c-06d1-4913-bb29-d59439e73c0f` and successfully stored decision `858bf5b8-9c0e-49fe-a965-1b9eeb743825` through `log_decision`.
- Verified `python -m compileall -q backend mcp_server` and `.venv\Scripts\python.exe -m pytest backend\tests\test_mcp_contract.py -q`: 2 passed.

## 2026-07-17 - Global install and attach workflow started

- Added the first global-install path: the MCP now sends its configured `ATLAS_PROJECT_NAME` to the API when creating the default project, so one running Atlas API can serve many attached Codex projects without logging everything under the API install folder's project name.
- Added `atlas attach`, which writes a project-local `.codex/config.toml` pointing to the shared Atlas install and setting `[mcp_servers.atlas.env] ATLAS_PROJECT_NAME`.
- Updated `atlas setup` through `atlas.cmd` to create `.venv` automatically when it is missing, then run the existing setup flow inside that environment.
- Added optional `ATLAS_DASHBOARD_PIN` protection for non-health API access; the dashboard prompts for the PIN and the MCP sends it automatically when configured.
- Captured the roadmap in `docs/GLOBAL_INSTALL_AND_ATTACH_PLAN.md`. Verified `python -m compileall -q backend mcp_server` and `.venv\Scripts\python.exe -m pytest backend\tests -q --basetemp work\atlas-pytest`: 36 passed.

## 2026-07-17 - Install packaging and stop command started

- Added `atlas stop`, which stops the configured local Atlas API only after confirming the health endpoint identifies as `atlas-api`.
- Added `install-atlas.ps1` as the first Windows packaging path. It copies Atlas program files to a stable install folder, skips local state like `.env`, `.venv`, `.codex`, `.git`, and `work`, creates `.venv`, and can add the install folder to the user PATH.
- Updated README and the runbook to describe install-once, attach-many, PATH usage, `atlas stop`, and optional dashboard PIN behavior. Automatic idle shutdown remains deferred.
- Verified `python -m compileall -q backend mcp_server`, `install-atlas.ps1` PowerShell parsing, `atlas stop` on an empty port, and `.venv\Scripts\python.exe -m pytest backend\tests -q --basetemp work\atlas-pytest`: 36 passed.

## 2026-07-17 - Installer PATH correction and packaging direction

- Fixed `install-atlas.ps1` so a failed `py -3.11` probe does not abort the installer before the PATH prompt. This matched the observed install log where setup continued manually but PATH was never added.
- Refreshed the installed `C:\Users\Admin\Atlas` folder and set the normal Admin user PATH to include `C:\Users\Admin\Atlas`; open a new terminal before using `atlas` from another project.
- Added `packaging/windows/` with an Inno Setup script and packaging notes. Inno Setup is the recommended first EXE installer path; MSI/WiX is deferred until Atlas needs enterprise installer behavior.
- Recorded editable memory as the next feature slice: API/dashboard/tool edits must recompute embeddings and rebuild the running summary instead of editing raw rows only.

## 2026-07-17 - Editable memory and installer-location safety

- Implemented project-scoped saved-memory editing through `PATCH /api/v1/decisions/{decision_id}`, the dashboard's Edit memory form, and the MCP `edit_memory` tool. Each save recomputes the embedding and rebuilds the running summary from the project's current decisions.
- Kept MCP edits intentionally ID-based: use `search` to find a memory, then call `edit_memory` with its exact ID. This avoids changing a fuzzy match by mistake.
- Updated the Inno Setup path so it passes the chosen `{app}` install directory to PATH setup, avoids a hidden PowerShell prompt, and excludes previous installer output from the package source. A later `atlas attach` always writes the actual install location into that project's Codex config.
- Verified focused storage and MCP tests: 8 passed.

## 2026-07-17 - Submission materials audit

- Rewrote `docs/DEMO_SCRIPT.md` as a real screen-and-voice recording plan under three minutes, including fresh-task recall, conflict warning, decision capture, dashboard evidence, and one saved-memory edit.
- Added `docs/BUILD_WEEK_SUBMISSION_CHECKLIST.md` with the remaining Devpost material, developer-tool judge path, and final proof steps.
- Current verification baseline is 37 passing backend tests. The remaining delivery work is a live recorded end-to-end run, public YouTube upload, Devpost fields, and a compiled Windows installer if Inno Setup is installed.
- Refreshed `README.md` with the current SQLite judge quick start, automatic API-start explanation, dashboard path, and `edit_memory` tool. Added `docs/DEVPOST_SUBMISSION.md` as a ready-to-paste submission description and links checklist.
- Compiled the Inno Setup installer at `packaging/windows/Output/AtlasSetup.exe`. The README now makes the EXE the preferred Windows judge path; publish it as a GitHub Release asset before submission.
- Clarified trusted-team cloud sharing: each teammate uses the same cloud PostgreSQL URL and project name but runs `atlas attach` locally, so no absolute-path Codex config is copied between computers. Documented Docker ownership, the `atlas-db` container, automatic versus manual startup, and the local `5434 -> 5432` port mapping. Fixed manual Docker setup to apply the schema after the user starts the supplied container.

## Deferred to v2

- Knowledge graphs, confidence scoring, time travel, full CLI, background watching, multi-model sharing, linked-project memory, and recency/importance weighting.
