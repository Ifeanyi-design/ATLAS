# Atlas - Devpost Submission Draft

Use this as the starting text for the Devpost submission. Replace bracketed placeholders before publishing.

## Project name

Atlas

## Tagline

Durable engineering decisions for Codex, with conflict warnings before a project drifts.

## Track

Developer Tools

## What I built

Atlas is an MCP-powered engineering-memory layer for Codex. Long-running software projects often lose the rationale behind earlier decisions when a new coding task begins. Atlas stores material decisions, their reasons, affected files, and optional design context as project-scoped memory.

Before work begins, a Codex task can retrieve only the saved decisions relevant to the new request. If the request contradicts a prior architectural choice, Atlas returns the earlier decision and its rationale as a warning. The developer stays in control: they can override the warning with a recorded reason. A local dashboard makes the decision timeline, conflicts, design context, and editable saved memory visible.

## How it works

1. Codex calls Atlas MCP tools to retrieve context, log a material decision, search memory, edit a saved memory, or record a conflict override.
2. Atlas stores each project's memory separately in SQLite or PostgreSQL with pgvector support.
3. The dashboard provides a human-readable audit trail and lets the developer safely correct saved memory.
4. The local API starts on demand when Atlas is used; it is not a background transcript recorder.

## Why it matters

AI coding agents are useful but fresh tasks can lose the engineering reasons behind a project. Atlas gives those tasks the relevant architectural context before implementation, helping teams avoid repeated debates and accidental reversals without dumping every old conversation into the prompt.

## Built with Codex and GPT-5.6

I used Codex with GPT-5.6 throughout the Build Week implementation: architecture planning, FastAPI and MCP development, dashboard iteration, installation workflow design, test creation, debugging, documentation, and demo preparation. The project also includes an optional OpenAI API mode for richer decision extraction, embeddings, summaries, curation, and conflict checks; its offline SQLite mode keeps the judge path self-contained.

## How to test

The preferred Windows judge path is the `AtlasSetup.exe` installer published with the project release. It installs Atlas, creates its Python environment, guides the judge through SQLite setup, and lets them attach any small project with `atlas attach`. The README also includes a source fallback. No Docker, cloud database, or frontend build is required.

## Links to enter in Devpost

- Demo video: [PASTE PUBLIC YOUTUBE URL]
- Code repository: https://github.com/Ifeanyi-design/ATLAS
- Windows installer: [PASTE GITHUB RELEASE DOWNLOAD URL FOR AtlasSetup.exe]
- Codex feedback session ID: [PASTE ID RETURNED BY /feedback]
