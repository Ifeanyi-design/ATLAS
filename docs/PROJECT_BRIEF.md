# Atlas v1 — Durable Project Brief

Read this document, [`PLAN.md`](PLAN.md), and [`PROGRESS.md`](PROGRESS.md) at the start of every Codex session before making changes.

## Mission and deadline

Build **Atlas**, an engineering context layer for Codex, for OpenAI Build Week (Developer Tools track). Submission is due **July 21 at 5:00 PM Pacific**.

Atlas captures architectural decisions Codex makes during sessions, scopes them to a project, retrieves only relevant prior decisions for new work, and flags when a new prompt contradicts a prior decision.

## North Star principle

**Atlas reduces developer cognitive load; it must not create manual maintenance or a new workflow.** Prefer automatic capture and useful defaults. If a proposed feature adds effort without clearly reducing it elsewhere, defer it.

## Architecture

```text
Codex ──MCP──> Atlas MCP server ──> FastAPI service ──> SQLite (local) or PostgreSQL + pgvector
                         │                    │
                         └────────────────────┴──> low-cost model calls
                                              (extract, curate, summarize, check conflicts)
```

- **MCP server:** exposes `log_decision`, `get_context`, `search`, and a deliberate `override_conflict` action to Codex.
- **FastAPI:** owns validation, orchestration, project isolation, and dashboard API endpoints.
- **SQLite or PostgreSQL + pgvector:** stores project-scoped decisions, structured UI/design context, summaries, conflicts, and embeddings. Local SQLite uses JSON embeddings with deterministic in-process cosine ranking; PostgreSQL keeps indexed pgvector retrieval for shared/team use.
- **Low-cost model:** produces structured decision extraction, bounded retrieval curation, incremental summary updates, and conflict checks.

## MCP workflow and lifecycle

Atlas is not a background watcher. Codex deliberately invokes its MCP tools at the relevant moments:

```text
New user prompt
      │
      ▼
Codex calls get_context(project_id, prompt, fresh_session)
      │
      ├─ Atlas retrieves project-scoped candidates, curates them, and checks conflicts
      ├─ Atlas adds the running summary and, for UI work, direct structured design context
      └─ Fresh-session mode returns no injected memory
      ▼
Codex works on the task
      │
      ├─ If needed, Codex calls search(project_id, query) for mid-task recall
      ▼
Codex recognizes a material engineering decision was made
      │
      ▼
Codex calls log_decision(project_id, session_id, exchange)
      │
      ├─ Atlas extracts validated structured data
      ├─ Stores nothing if no real decision occurred
      ├─ Creates and stores the embedding and structured UI context when applicable
      └─ Incrementally updates the running project summary
```

The project-local MCP server creates the configured project on its first call and maintains a session ID for its process. Tool callers do not normally supply opaque IDs; optional IDs remain available for an intentional cross-project or session action.

## V1 scope — build this and nothing more

1. An MCP server exposing `log_decision`, `get_context`, `search`, and `override_conflict` for deliberate, auditable conflict exceptions.
2. Automatic decision extraction: a small/low-cost model turns an exchange into validated structured JSON and stores nothing if no real decision occurred.
3. User-selectable storage: local SQLite without Docker, local PostgreSQL with Docker, or a supplied PostgreSQL URL. All reads and writes are strictly `project_id` scoped.
4. Retrieval: pgvector returns 15–20 candidates; a small model curates a bounded relevant set.
5. A running project summary updated incrementally when a decision is logged—never regenerated for every prompt.
6. Conflict detection: compare a new prompt with retrieved candidates and cite the original decision plus reason on contradiction.
7. Fresh-session mode: skip context injection for that session but continue logging new decisions.
8. Mid-task recall: Codex can call `search()` again when it seems to be missing context.
9. Design/UI context: store structured JSON (for example colors, spacing, component patterns) and file paths separately from prose; directly inject it, without summarization, for UI-related prompts.
10. A single dashboard page with decision timeline, project filter plus optional date range, live conflict panel, and a token-savings counter that compares fresh-session context to an equivalent long-session baseline.

## Explicitly not in v1

Do not implement knowledge graphs, confidence scores, time-travel views, a full CLI, live background session watching, multi-model (Claude/Gemini) sharing, linked-project memory, or recency/importance weighting. If an idea is useful but out of scope, place it in the **Deferred to v2** section of `PROGRESS.md` and continue with v1.

## Atlas roadmap (not a v1 commitment)

### V2

- Smarter ranking, linked projects, customizable capture rules, and richer engineering memory.

### V3

- Knowledge graph, multi-model memory, team collaboration, and broader project intelligence.

## Required technical direction

- Backend: FastAPI.
- Persistence: SQLite for local projects, or PostgreSQL + pgvector for shared/team projects, with SQLAlchemy ORM and migrations.
- Integration: an MCP server serving the four Atlas tools to Codex.
- Intelligence calls: use a lightweight/cheap model for extraction, candidate curation, incremental summary updates, and conflict checking.
- Core tables: `projects`, `sessions`, `decisions`; v1 may add narrowly supporting `design_contexts` and `conflict_events` tables.

## Non-negotiable behavior

- Do not write a decision record when the exchange has no material engineering decision.
- Never leak results across projects.
- Treat retrieval, the running summary, and direct UI/design JSON as three separate context mechanisms.
- Only direct-inject structured design context for a UI-related prompt; do not turn it into prose first.
- A conflict must cite the prior decision and the reason it was made. It is a warning, not a silent hard block: an override requires an explicit reason and is retained for audit.
- Fresh-session mode means **no injection**, not “no memory collection.”

## How to work in this repository

1. Read this brief, `PLAN.md`, and `PROGRESS.md` first.
2. Work through the plan in order unless a real blocker requires a documented deviation.
3. Before writing code, identify the current plan checkbox or checkboxes being addressed.
4. After meaningful progress, update `PLAN.md` and append a brief dated note to `PROGRESS.md`: completed work, deviation and reason if any, and next step.
5. Keep changes narrowly inside v1. Test the feature proportionally before marking it complete.
6. For every new session, the user can simply say: **“Read the docs first, then continue Atlas.”**

## Model and reasoning operating guide

Use the lowest model/reasoning setting that can safely complete the work, then escalate when the task genuinely needs it.

| Workflow task | Recommended model | Reasoning effort |
|---|---|---|
| Creating files, simple FastAPI routes, migrations, routine CRUD, tests, documentation, small bug fixes | GPT-5.6 Terra | Low or Medium |
| Implementing an established plan phase with a few connected files | GPT-5.6 Terra | Medium |
| Designing the initial data model, MCP tool contracts, retrieval boundaries, embedding/query correctness, integration debugging | GPT-5.6 Terra or the highest available Codex model | High |
| Resolving an architecture trade-off, a subtle cross-project/privacy issue, broken end-to-end demo flow, or final code review | Highest available Codex model | High; use Max only if High fails after a focused attempt |
| Simple status checks, checkbox/log updates, narrow copy edits | GPT-5.6 Terra | Low |

Default for Atlas: **GPT-5.6 Terra at Medium**. Switch to a higher reasoning setting before irreversible or cross-cutting decisions, and switch back to the default when the architecture is settled. Do not start at Max: it costs more time and budget and is unlikely to improve routine implementation. Raise reasoning one level only when the current attempt is missing dependencies, producing inconsistent changes, or failing to diagnose a non-obvious issue; record any major approach change in `PROGRESS.md`.

Current model availability and controls depend on the Codex plan and workspace. The submission should truthfully cite the GPT-5.6/Codex sessions that materially contributed to Atlas.

## Suggested starting prompt for a new Codex session

```text
Read /docs/PROJECT_BRIEF.md, /docs/PLAN.md, and /docs/PROGRESS.md first. Then continue Atlas from the next unchecked task. Follow the v1 scope and guardrails exactly. Before coding, state which plan checkbox you are addressing. After meaningful work, update PLAN.md and append a concise dated entry to PROGRESS.md. Use GPT-5.6 Terra at Medium by default; tell me before any cross-cutting architecture, retrieval correctness, privacy/isolation, or difficult debugging decision needs a higher reasoning setting.
```
