# Atlas runbook in plain English

This is the non-mystical version of how Atlas runs.

## The story

Imagine you are a developer opening your laptop in the morning.

Atlas has three pieces:

1. **The database** is the notebook. It stores the memories.
2. **The Atlas API** is the librarian. It knows how to read and write the notebook.
3. **The Atlas MCP server** is the assistant at your Codex desk. Codex talks to it through MCP tools.

You normally do **not** start the MCP server yourself. Codex starts it from `.codex/config.toml` when you open a fresh task in this project. The MCP server then starts the local Atlas API when it needs it.

What you may need to start yourself is the database dependency:

- SQLite: nothing to start.
- Cloud PostgreSQL: nothing local to start, but internet/database access must work.
- Docker PostgreSQL: Docker Desktop must be running.

## The short commands

From the Atlas install folder in PowerShell, use:

```powershell
.\atlas setup
.\atlas attach C:\path\to\project --project-name project-name
.\atlas doctor
.\atlas stop
```

`setup` is only for first-time setup or changing storage. It asks you to choose SQLite, local Docker PostgreSQL, or an existing cloud PostgreSQL database. When you choose cloud PostgreSQL, it asks for the database URL and saves it in this project's `.env` file.

`attach` writes a project-local `.codex/config.toml` so Codex can start the shared Atlas MCP server for that project. It also writes `ATLAS_PROJECT_NAME` into the MCP env block, so a shared API keeps project memory separated by name and ID.

`doctor` only checks the setup. It does not change your memory or database.

`stop` stops the local Atlas API when it is listening on the configured local port and identifies as `atlas-api`.

For normal daily use, you usually do not need to run a command. Start Docker Desktop first only if you chose Docker PostgreSQL, then open a fresh Codex task.

## Normal daily flow

There are two different flows: first-time setup and normal daily use.

First-time setup means Atlas has not written `.env` and `.codex/config.toml` for this project yet. Daily use means setup is already done and you are only opening Codex to use memory.

### SQLite

First time:

1. Run `.venv\Scripts\python.exe backend\scripts\setup.py`.
2. Choose SQLite.
3. Open Codex in the Atlas project.
4. Open a fresh task and check `/mcp`.

Daily use:

1. Open Codex in the Atlas project.
2. Open a fresh task.
3. Type `/mcp` and confirm `atlas` is listed.
4. Use Atlas.

### Cloud PostgreSQL

First time:

1. Make sure the internet is working and the database URL is ready.
2. Run `.venv\Scripts\python.exe backend\scripts\setup.py`.
3. Choose Existing PostgreSQL URL.
4. Open Codex in the Atlas project.
5. Open a fresh task and check `/mcp`.

Daily use:

1. Make sure the internet/database is reachable.
2. Open Codex in the Atlas project.
3. Open a fresh task.
4. Type `/mcp` and confirm `atlas` is listed.
5. Use Atlas.

### Shared cloud project for a team

This works today for a trusted team. Every member runs their own local Atlas MCP/API process, but those local processes use the same cloud PostgreSQL database and the same Atlas project name. That means they resolve the same `projects` row and share its saved decisions.

Each teammate should do this on their own computer:

```powershell
# First, install Atlas and run `atlas setup`.
# Choose Existing PostgreSQL URL and use the team's shared database URL.
cd C:\path\to\the\cloned-team-project
atlas attach . --project-name bizlive-dashboard
```

Use exactly the same project name for the same shared room. Do **not** copy another person's `.codex/config.toml`, because it contains that person's absolute Atlas install path. `atlas attach` writes the correct local path for each teammate.

The first person initializes the database schema. Later teammates can use the same cloud URL without running migrations again. Atlas v1 is a trusted-team setup: anyone with the cloud database credentials and the project name can access that project memory. It does not yet have per-user roles or project-level access control.

### Docker PostgreSQL

First time:

1. Start Docker Desktop.
2. Wait until Docker says it is running.
3. Run `.venv\Scripts\python.exe backend\scripts\setup.py`.
4. Choose Local PostgreSQL.
5. Open Codex in the Atlas project.
6. Open a fresh task and check `/mcp`.

Daily use:

1. Start Docker Desktop.
2. Wait until Docker says it is running.
3. Open Codex in the Atlas project.
4. Open a fresh task.
5. Type `/mcp` and confirm `atlas` is listed.
6. Use Atlas.

#### What the Docker choices mean

- **Option 1 - Atlas starts Docker:** Atlas runs `docker compose up -d --wait db` when an Atlas tool is used. Docker Desktop itself still has to be installed and running. In Docker Desktop, the database appears as the `atlas-db` container.
- **Option 2 - I start Docker myself:** from the Atlas install folder, run `docker compose up -d db`, then run `atlas setup` and choose option 2. Atlas applies its schema but will not automatically restart the container later.

The supplied local Compose setup maps host port **5434** to PostgreSQL's container port **5432**. Atlas therefore expects this local database URL:

```text
postgresql+psycopg://atlas:atlas@127.0.0.1:5434/atlas
```

You can inspect the container, port mapping, and logs in Docker Desktop. `atlas doctor` also reports whether Docker is installed, the daemon is reachable, and whether Atlas is configured for managed Docker.

If something feels wrong, run:

```powershell
.venv\Scripts\python.exe backend\scripts\doctor.py
```

## Do I run a command before opening Codex?

Usually, no.

Run a command before opening Codex only when you are setting up or debugging:

- First setup: `.venv\Scripts\python.exe backend\scripts\setup.py`
- Health check: `.venv\Scripts\python.exe backend\scripts\doctor.py`
- Tests: `.venv\Scripts\python.exe -m pytest backend\tests -q`

For normal use, start the database dependency if needed, then open Codex.

## Sleep, shutdown, and restart

### Sleep

Sleep is like pausing a movie. Windows may keep Docker, ports, and processes alive, or it may quietly break one of them. After wake:

1. Try Atlas normally.
2. If it fails, run the doctor.
3. If Docker is the issue, restart Docker Desktop.
4. Open a fresh Codex task so MCP reconnects cleanly.

Your memory is still in the database.

### Shutdown

Shutdown closes the movie. Local API and MCP processes stop. Docker Desktop also stops. After boot:

1. Start Docker Desktop if using Docker PostgreSQL.
2. Open Codex in the Atlas project.
3. Open a fresh task.
4. Check `/mcp`.

Your memory is still in SQLite, Docker's Postgres volume, or cloud Postgres.

### Restart

Restart is shutdown plus boot. Treat it the same as shutdown:

1. Start Docker Desktop if needed.
2. Open Codex.
3. Open a fresh task.
4. Check `/mcp`.

## Which database should I use for Build Week?

Use **cloud PostgreSQL** if you can set it up quickly and reliably. It avoids Docker Desktop drama during the demo.

Use **SQLite** if you need the fastest, lowest-stress demo. It proves the product story, but it is less impressive for production/storage credibility.

Use **Docker PostgreSQL** if you want a realistic local setup and Docker is behaving on the machine you will demo from.

My Build Week recommendation:

1. Cloud PostgreSQL for the final demo.
2. SQLite as the emergency fallback.
3. Docker PostgreSQL only if Docker Desktop is stable that day.

## Using Atlas in another project

Atlas is project-scoped, but the Atlas code does not need to live inside every project. The preferred workflow is one install folder and many attached projects.

One-time install:

```powershell
.\install-atlas.ps1 -InstallDir "$env:USERPROFILE\Atlas"
cd "$env:USERPROFILE\Atlas"
.\atlas setup
```

Per project:

```powershell
atlas attach C:\path\to\project --project-name project-name
```

If Atlas is not on PATH, use the full path:

```powershell
C:\Users\Admin\Atlas\atlas attach C:\path\to\project --project-name project-name
```

The important part is `.codex/config.toml`: Codex needs that file in the project it opens so it knows how to start the Atlas MCP server. The attached config points to the shared Atlas install and passes the project name through `[mcp_servers.atlas.env]`.

## Why not build a background service now?

The shared install and `attach` workflow give Atlas one install folder and many project rooms. A true always-on background service is a separate product step because it changes the surface:

- installer or background service
- cross-project identity
- project discovery
- auth and local permissions
- upgrade and uninstall story
- more failure modes during the demo

The current path keeps the simpler Codex-started MCP/API lifecycle. A background Windows service, tray app, or setup UI can come later after the command workflow is stable.

## Should the UI be prettier?

Yes, but only polish now.

Good v1 UI improvements:

- clearer tabs for Timeline, Conflicts, Design Context, System
- stronger empty states
- a visible "doctor status" panel
- cleaner demo-friendly spacing and typography

Risky v1 UI improvements:

- full redesign
- animations
- complex charts
- settings pages that do not change real behavior
- multi-project/global admin screens

For Build Week, the UI should make the story obvious in under five minutes.
