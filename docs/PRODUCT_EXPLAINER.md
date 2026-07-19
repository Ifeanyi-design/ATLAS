# Atlas product explainer and test playbook

This is the practical "know the product" guide for demo prep and judge Q&A.

## What Atlas is

Atlas is a project-scoped engineering memory layer for Codex. It does not watch every message in the background. Codex explicitly calls Atlas MCP tools when it needs memory, search, decision capture, editing, removal, or a conflict override.

The core promise is simple: a fresh Codex task can recover the decisions and reasons that matter for the current project, without replaying an entire old chat.

## Runtime pieces

Atlas has three runtime pieces:

1. The Atlas MCP server exposes tools to Codex.
2. The local FastAPI service owns validation, database access, dashboard API routes, and static dashboard serving.
3. The database stores projects, sessions, decisions, embeddings, structured design context, summaries, and conflict events.

Codex starts the MCP server from the attached project's `.codex/config.toml`. The MCP server starts the FastAPI service on demand when a tool is called. The API then reads or writes SQLite or PostgreSQL depending on `.env`.

## One install, many projects

The recommended local workflow is one Atlas install folder shared by many Codex projects.

Each project runs:

```powershell
atlas attach C:\path\to\project --project-name project-name
```

That writes the project-local `.codex/config.toml` with:

- the absolute path to the installed Atlas Python executable;
- `cwd` set to the Atlas install folder;
- `ATLAS_PROJECT_NAME` set for that attached project.

It also creates or updates the active Codex instruction file for that folder. If `AGENTS.override.md` exists, Atlas updates it because Codex gives that file priority. Otherwise Atlas uses `AGENTS.md`. The Atlas section is wrapped in markers so rerunning attach can refresh only that block without replacing the user's existing project guidance.

The first MCP tool call asks the API for the default project using that project name. The API creates or reuses one row in `projects`, then all future reads and writes use that `project_id`.

## Install-relative storage

SQLite is intentionally stored under the Atlas install folder, not inside every attached project.

Fresh setup writes an absolute SQLite URL like:

```text
sqlite:///C:/Users/Admin/Atlas/work/atlas.db
```

Older `.env` files that still say `sqlite:///./work/atlas.db` are normalized at runtime against the Atlas install folder, so a command launched from another directory still uses the install database.

Runtime state to preserve during reinstall:

- `.env`
- `.venv`
- `work`

Program files that can be safely refreshed during reinstall:

- `backend`
- `dashboard`
- `docs`
- `infra`
- `mcp_server`
- `packaging`
- root files such as `atlas.cmd`, `install-atlas.ps1`, `requirements.txt`, `README.md`

## SQLite versus PostgreSQL plus pgvector

SQLite mode is the lowest-friction demo path. Atlas stores embeddings as JSON arrays in SQLite and ranks candidates in Python using cosine distance. There is no Docker, no network, and no pgvector index. This is ideal for a judge test path or emergency demo fallback.

PostgreSQL mode is the production-like path. Atlas stores embeddings in a `vector(1536)` column using pgvector. Retrieval is filtered by `project_id`, ordered by `embedding.cosine_distance(query_embedding)`, and limited to the top candidates. Migrations create the tables and pgvector index.

Both storage modes use the same SQLAlchemy models and API contracts:

- `projects`: project name, running summary
- `sessions`: one Codex/MCP process session per project
- `decisions`: durable decision, reason, affected files, embedding
- `design_contexts`: structured UI/design JSON and file paths
- `conflict_events`: detected contradiction, status, override reason

## Intelligence modes

Atlas has two intelligence modes.

Offline mode is used when `ATLAS_OPENAI_API_KEY` is not set. It is deterministic and no-cost:

- explicit `Decision:` and `Reason:` markers are easiest to capture;
- embeddings are hashed local vectors;
- curation and conflict detection are lexical/rule-based;
- no network calls are made.

OpenAI mode is used when `ATLAS_OPENAI_API_KEY` is set:

- model extraction turns natural conversation into structured decision JSON;
- embeddings come from the configured embedding model;
- model curation chooses the most relevant retrieved candidates;
- model conflict checking reasons over the candidate set, with offline fallback if a call fails;
- summaries are model-written instead of mechanically appended.

Storage mode and intelligence mode are separate. You can run SQLite with OpenAI intelligence, PostgreSQL with offline intelligence, or any other combination.

## What happens when `log_decision` is used

1. Codex calls the MCP tool `log_decision(exchange)`.
2. The MCP server ensures the API is running.
3. The MCP server resolves the configured project name to a `project_id`.
4. The API validates `project_id`, `session_id`, and the exchange.
5. The intelligence layer extracts structured data:
   - `is_real_decision`
   - `decision`
   - `reason`
   - `affected_files`
   - optional `design_context`
6. If no real decision exists, Atlas returns `accepted=false` and stores nothing.
7. If a decision exists, Atlas embeds the decision and reason.
8. Atlas creates or reuses the session row.
9. Atlas inserts a row in `decisions`.
10. If design context exists, Atlas inserts a row in `design_contexts`.
11. Atlas updates the project's running summary.
12. The API commits the transaction and returns the decision ID plus summary.

Main code paths:

- `mcp_server/server.py`
- `backend/app/api/routes.py`
- `backend/app/decision_capture.py`
- `backend/app/intelligence.py`
- `backend/app/models.py`

## What happens when `get_context` is used

1. Codex calls `get_context(prompt, fresh_session=false)`.
2. The MCP server ensures the API is running and resolves the project.
3. If `fresh_session=true`, Atlas returns no injected decisions and no design context.
4. Otherwise, Atlas embeds the new prompt.
5. Atlas retrieves 15 to 20 project-scoped candidates:
   - SQLite ranks JSON embeddings in Python.
   - PostgreSQL ranks with pgvector cosine distance.
6. Atlas curates the candidate list down to a small selected set.
7. Atlas adds the running project summary separately from selected decisions.
8. Atlas checks whether the new prompt contradicts the selected decisions.
9. If a conflict is found, Atlas inserts a `conflict_events` row and returns the original decision and reason.
10. If the prompt is UI-related, Atlas direct-injects matching structured design context.

Main code paths:

- `backend/app/retrieval.py`
- `backend/app/intelligence.py`
- `backend/app/dashboard.py`

## What happens when `search` is used

`search(query, limit)` is explicit mid-task recall. It embeds the query, retrieves project-scoped vector candidates, and returns matching saved decisions. It does not update the running summary and does not create conflict events.

## What happens when memory is edited or removed

`edit_memory` updates a saved decision, reason, or affected files. Atlas recomputes the embedding and rebuilds the project summary from remaining current decisions.

`remove_memory` deletes selected memories, a time range, or all project memory with exact confirmation. Related design context and relevant conflict rows are cleaned up, and the project summary is rebuilt.

## What happens when a conflict is overridden

Atlas never silently blocks a requested change. It warns. If the developer deliberately wants to continue, Codex calls:

```text
override_conflict(conflict_event_id, reason)
```

Atlas marks the conflict event as `overridden`, stores the reason, and keeps the audit trail visible in the dashboard.

## How to test Atlas yourself

### 1. Compile and install

From the source repo, compile:

```text
packaging\windows\atlas.iss
```

Install the generated EXE. Choose a stable install folder such as:

```text
C:\Users\Admin\Atlas
```

Run setup and choose SQLite first:

```powershell
cd C:\Users\Admin\Atlas
atlas setup
atlas doctor
```

Doctor should pass Python, dependencies, config, settings, database connectivity, and SQLite schema initialization. API reachability can warn before the first MCP tool call.

### 2. Attach a test project

```powershell
mkdir C:\Users\Admin\Documents\testing
cd C:\Users\Admin\Documents\testing
atlas attach . --project-name tester21
```

Open a fresh Codex task in that folder and check `/mcp`. Atlas should be listed.

### 3. Log a decision

Ask Codex to call Atlas with:

```text
Decision: Use PostgreSQL with pgvector for shared Atlas memory.
Reason: It gives project-scoped vector retrieval and a realistic production storage story.
Affected file: backend/app/db.py
```

Expected result: `accepted=true`, `status=stored`, a decision ID, and a running summary.

### 4. Retrieve context in a fresh task

Open another fresh Codex task in the same attached project and ask:

```text
Use Atlas context before adding semantic search to customer notes.
```

Expected result: Atlas returns the running summary and the PostgreSQL/pgvector decision.

### 5. Trigger a conflict

Ask:

```text
Replace PostgreSQL with MongoDB for Atlas memory.
```

Expected result: Atlas warns with the original PostgreSQL decision and reason. It does not block; it creates a conflict event.

### 6. Show the dashboard

Open:

```text
http://127.0.0.1:8000/dashboard/
```

Expected result: project selection, timeline, conflict, design context if captured, storage mode, intelligence mode, and estimates.

### 7. Inspect storage directly

For SQLite, the DB is:

```text
C:\Users\Admin\Atlas\work\atlas.db
```

You can inspect it with any SQLite viewer, or with Python:

```powershell
C:\Users\Admin\Atlas\.venv\Scripts\python.exe -c "import sqlite3; con=sqlite3.connect(r'C:\Users\Admin\Atlas\work\atlas.db'); print(con.execute('select name from sqlite_master where type=''table'' order by name').fetchall())"
```

For PostgreSQL, inspect tables with `psql` or a database GUI. The local Docker database maps host port `5434` to container port `5432`.

## Common judge questions

**Is Atlas permanent memory?**  
No. It is project-scoped engineering memory stored in a local or configured database. It is explicit, inspectable, editable, and removable.

**Does Atlas read every Codex message?**  
No. Codex calls Atlas tools deliberately. Atlas stores only extracted durable decisions, not full transcripts.

**How do you prevent project leakage?**  
Every query is filtered by `project_id`. Attached projects resolve to separate project rows through `ATLAS_PROJECT_NAME`.

**Why SQLite and PostgreSQL?**  
SQLite gives a no-dependency test path. PostgreSQL plus pgvector gives a realistic shared/team retrieval path.

**What is pgvector doing?**  
It stores embeddings in a vector column and lets PostgreSQL perform indexed cosine-distance search for the nearest prior decisions in the same project.

**What happens without an OpenAI API key?**  
Atlas still works offline with explicit decision markers, hashed deterministic embeddings, local ranking, and lexical conflict checks.

**Does Atlas block a conflicting request?**  
No. It warns and records an auditable override if the developer continues.
