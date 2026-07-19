# Atlas - Devpost Submission Draft

Use this as a starting outline, not as paste-and-submit copy. Rewrite the final Devpost description in your own voice, then replace bracketed placeholders before publishing.

## Project name

Atlas

## Tagline

Project memory for Codex, with warnings before old decisions get reversed.

## Track

Developer Tools

## What I built

Atlas is a project memory tool for Codex. I built it because I kept seeing the same problem during longer coding work: a new task may know the files, but not the reasons behind earlier decisions. Atlas stores important decisions, their reasons, affected files, and optional design context for each project.

Before work begins, Codex can ask Atlas for the saved decisions that matter to the current request. If the request contradicts a prior architecture choice, Atlas returns the earlier decision and reason as a warning. The developer stays in control: they can override the warning with a recorded reason. A local dashboard shows the decision timeline, conflicts, design context, and editable saved memory.

## How it works

1. Codex calls Atlas MCP tools to retrieve context, log a material decision, search memory, edit a saved memory, or record a conflict override.
2. Atlas stores each project's memory separately in SQLite or PostgreSQL with pgvector support.
3. The dashboard provides a human-readable audit trail and lets the developer safely correct saved memory.
4. The local API starts on demand when Atlas is used; it is not a background transcript recorder.

## Why it matters

AI coding agents are useful, but fresh tasks often lose the "why" behind a project. Atlas brings back the relevant reasons before implementation, without dumping every old conversation into the prompt.

## Built with Codex and GPT-5.6

I used Codex with GPT-5.6 during the Build Week implementation: planning the architecture, building the FastAPI and MCP pieces, iterating on the dashboard, designing the installer flow, writing tests, debugging, and preparing the demo. Atlas also has an optional OpenAI API mode for richer extraction, embeddings, summaries, curation, and conflict checks. The SQLite mode keeps the judge path self-contained.

## How to test

The preferred Windows judge path is the `AtlasSetup.exe` installer published with the project release. It installs Atlas, creates its Python environment, guides the judge through SQLite setup, and lets them attach any small project with `atlas attach`. The README also includes a source fallback. No Docker, cloud database, or frontend build is required.

## Supported test environment

The packaged Build Week path is tested for Windows 10/11 x64 with PowerShell and Codex Desktop. Python 3.11 or newer must be installed so the installer can create Atlas's `.venv`. Docker Desktop is optional and only needed for local Docker PostgreSQL; SQLite requires no Docker, cloud database, frontend build, or OpenAI API key.

## Links to enter in Devpost

- Demo video: [PASTE PUBLIC YOUTUBE URL]
- Code repository: https://github.com/Ifeanyi-design/ATLAS
- Windows installer: [PASTE GITHUB RELEASE DOWNLOAD URL FOR AtlasSetup.exe]
- Codex feedback session ID: [PASTE ID RETURNED BY /feedback]
