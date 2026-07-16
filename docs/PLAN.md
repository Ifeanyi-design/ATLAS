# Atlas v1 Implementation Plan

**Target:** OpenAI Build Week — Developer Tools track  
**Submission deadline:** July 21, 5:00 PM Pacific  
**Product statement:** Atlas is an MCP-powered context layer for Codex that captures engineering decisions, retrieves only relevant memory for new tasks, and detects contradictions before they become repeated mistakes.

## Guardrails

- Build only the v1 scope in [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md).
- Do not add a feature after July 20. Record tempting ideas in `PROGRESS.md` under **Deferred to v2**.
- Every decision, approach change, and meaningful bug fix gets a short dated `PROGRESS.md` entry.
- At the start of every session, read this file and `PROGRESS.md` before taking action.
- Keep project data strictly scoped by `project_id`.

## Model and reasoning guide

- **GPT-5.6 Terra, Medium:** default for routine implementation, tests, docs, and small fixes.
- **GPT-5.6 Terra, High:** integrations, debugging that crosses components, migrations, and careful code review.
- **GPT-5.5, High:** architecture decisions, extraction/retrieval/conflict contracts, and a focused second opinion on a hard bug.
- Do not use Max/Ultra by default. Escalate only after a focused High-reasoning attempt fails.
- The current Codex app does not expose a model named “GPT-5.6 Sol”; use GPT-5.5 High for that high-capability role.

## Phase 0 — Project setup and foundation (Jul 15)

- [x] Create the repository structure: `backend/`, `mcp_server/`, `dashboard/`, `docs/`, `tests/`.
- [x] Add local development configuration, `.env.example`, and a concise `README.md` bootstrap section.
- [x] Create the FastAPI app with health check and versioned API router.
- [x] Provision PostgreSQL with the `vector` extension enabled.
- [x] Define SQLAlchemy models and migrations for `projects`, `sessions`, `decisions`, `design_contexts`, and `conflict_events`.
- [x] Add database indexes, including `project_id`, timestamps, and pgvector similarity index.
- [x] Build the MCP server skeleton and verify that Codex can enumerate its tools.
- [x] Add stub implementations for `log_decision`, `get_context`, and `search`.
- [x] Add a seed project and a smoke test that creates then reads a decision.
- [x] Add interactive storage setup: local PostgreSQL via Docker, an existing PostgreSQL URL, or local SQLite without Docker.
- [x] Make the MCP server start its local FastAPI dependency when needed.

**Exit check:** Local startup works; the database is migrated; all three MCP tools are visible and return valid stub-shaped responses.

## Phase 1 — Decision capture and extraction (Jul 16)

- [x] Define a strict extraction schema: `decision`, `reason`, `affected_files`, `design_context?`, `is_real_decision`.
- [x] Write the small-model extraction prompt and JSON validation/retry behavior.
- [x] Implement `log_decision(project_id, session_id, exchange)`.
- [x] Store nothing when `is_real_decision` is false.
- [x] Generate an embedding for each accepted decision and persist it with the row.
- [x] Extract UI/design context only when present, as structured JSON plus file paths.
- [x] Update the running project summary incrementally whenever a decision is saved.
- [x] Add unit tests: real decision, no decision, malformed response, file-path extraction, and design-context extraction.

**Exit check:** A sample coding exchange produces one validated decision, embedding, summary update, and—when relevant—structured design context.

## Phase 2 — Retrieval and context injection (Jul 17)

- [ ] Complete credits or any required Build Week task before noon Pacific.
- [x] Implement pgvector top-K retrieval of 15–20 candidates, filtered by `project_id`.
- [x] Add a bounded curator; it is deterministic offline and model-assisted when an API key is configured.
- [x] Keep retrieval and running summary separate in the response contract.
- [x] Implement `get_context(project_id, session_id, prompt, fresh_session)`.
- [x] When `fresh_session` is true, skip all injected memory but continue permitting future decision logging.
- [x] Detect UI-related prompts and attach matching design JSON directly, without summarizing it.
- [x] Add focused tests for project isolation boundaries, UI-context injection, and fresh-session behavior.
- [x] Serialize selected decisions and design context in a stable ID order after relevance selection, so repeated payloads are predictable.

**Exit check:** A new prompt receives only relevant context plus the existing running summary, and a fresh session receives neither while still capturing decisions.

## Phase 3 — Conflict detection and recall (Jul 18)

- [x] Define a conflict result contract: `has_conflict`, `new_intent`, `original_decision`, `original_reason`, `explanation`.
- [x] Compare the new prompt to retrieved candidates with a deterministic checker offline or a small-model checker when configured.
- [x] Store each detected conflict in `conflict_events` for the dashboard.
- [x] Return conflict information from `get_context` before context injection is applied.
- [x] Implement `search(project_id, query, limit)` for explicit mid-task recall.
- [x] Add tests for an actual contradiction, a compatible refinement, an unrelated prompt, and cross-project isolation.
- [x] Add explicit, reason-required conflict overrides and preserve them as auditable conflict-event state.

**Exit check:** A deliberately conflicting requirement is flagged with the earlier decision and its reason; `search()` retrieves the expected memory mid-task.

## Phase 4 — One-page dashboard (Jul 19)

- [x] Choose the smallest practical UI approach and connect it to the FastAPI API.
- [x] Build a decision timeline ordered newest first.
- [x] Add project selection and optional date-range filtering.
- [x] Build a live “conflict caught” panel from `conflict_events`.
- [x] Show conflict status and any deliberate override reason in the conflict panel.
- [x] Show the active storage mode, including SQLite’s local-ranking limitation, in the dashboard’s system state.
- [x] Add a transparent token-savings counter: fresh-session context tokens avoided versus an equivalent long-session baseline.
- [x] Make the UI design-context evidence visible for the demo (structured token/color/component example).
- [x] Add loading, empty, and error states.

**Exit check:** One page shows a project’s decisions, filter, conflict, and token-savings evidence without manual database inspection.

## Phase 5 — End-to-end demo path, polish, and submission (Jul 20–21)

- [x] Run the demo spine below end to end against a clean local database.
- [x] Fix setup reliability issues that block the demo: dependency reinstall noise, Windows Docker discovery, and opaque startup diagnostics.
- [x] Add an Atlas doctor command for environment, MCP config, Docker, database, migration, and API checks.
- [ ] Fix only defects, copy, reliability, and presentation issues on Jul 20; add no features.
- [x] Write setup, architecture, tool contract, privacy assumptions, and demo instructions in `README.md`.
- [ ] Exercise the install path on a clean machine profile: automatic Docker PostgreSQL, manual Docker PostgreSQL, existing PostgreSQL URL, and SQLite fallback. Recover to SQLite with a clear message if automatic local PostgreSQL startup fails.
- [ ] Record a short demo video showing the full story.
- [ ] Capture the Codex `/feedback` session ID.
- [ ] Finalize the submission before Jul 21, 5:00 PM Pacific.

### Demo spine (required)

- [x] Log a real architectural decision from a Codex exchange.
- [x] Start a different session and retrieve that decision for a related prompt.
- [x] Show a conflicting prompt being flagged with the prior reason.
- [x] Use `search()` for an explicit mid-task recall.
- [x] Show a UI prompt receiving structured design context directly.
- [x] Toggle fresh-session mode and show no injection but subsequent decision capture.
- [x] Open the dashboard to show the timeline, caught conflict, and token counter.

**Exit check:** The demo spine is reproducible in under five minutes and supports the product statement without explaining unbuilt features.

## Deferred to v2 (intentionally excluded)

- Knowledge graphs, confidence scores, time-travel views, full CLI suite, background session watching.
- Multi-model memory sharing, linked-project memory, recency/importance weighting.
- Any feature not listed above.
