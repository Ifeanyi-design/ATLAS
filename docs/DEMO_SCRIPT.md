# Atlas Build Week Demo Script

**Target length:** 2 minutes 40 seconds. Keep the final public YouTube video below 3 minutes.

**One-line message:** Atlas helps Codex remember the important decisions behind a project, even when you start a fresh task.

## Recording style

- Record the screen and narrate with your voice. A face camera is optional and not needed.
- Use one brief title card (about 3 seconds), then show the real Codex task and real dashboard. Do not use a slideshow instead of the product.
- Keep desktop notifications, credentials, unrelated tabs, and private project details hidden.
- Do not show installation in the video. The README and packaging material cover it; the video should prove the product works.

## Before recording

1. Use a small prepared demo project, not your real BizLive project.
2. Ensure the project has Atlas attached and that `/mcp` shows Atlas.
3. Pre-record two decisions: one PostgreSQL/pgvector architecture decision and one UI/design decision.
4. Start a fresh Codex task in that project, then make one Atlas call so the local API and dashboard are available.
5. Open the dashboard in a browser tab, but keep it behind Codex until the dashboard part of the demo.

## 0:00-0:12 - Problem and build context

**Visual:** Atlas title card, then a fresh Codex task.

**Say:**

> I used GPT-5.6 in Codex to plan and build Atlas: the MCP tools, FastAPI service, dashboard, tests, and installer flow. The problem is simple: a fresh coding task can lose the reasons behind earlier architecture decisions.

## 0:12-0:45 - Memory survives a fresh task

**Visual:** In the fresh task, ask Codex to retrieve Atlas context before adding semantic customer-note search.

**Show:** Atlas returning the running summary plus the prior PostgreSQL/pgvector decision and reason.

**Say:**

> This is a new task. Atlas brings back the saved decisions that matter here, instead of replaying a whole chat history.

## 0:45-1:20 - Catch a reversal before work begins

**Visual:** Ask to replace PostgreSQL with MongoDB, then show the Atlas conflict result.

**Show:** The original decision, reason, and conflict warning.

**Say:**

> Atlas recognizes that this request contradicts an earlier database decision. It warns with the prior choice and rationale. It does not secretly block the developer; an override remains possible and is recorded.

## 1:20-1:50 - Capture one new decision

**Visual:** Log an explicit UI decision through Atlas.

**Use this safe offline-demo text:**

```text
Decision: Keep the dashboard as a compact web interface with editable saved memory.
Reason: It makes project context easy to review and correct without leaving the browser.
Design context: {"components":["timeline","edit dialog"],"accent":"mint"}
Affected file: dashboard/app.js
```

**Say:**

> When a material decision is made, Atlas stores the decision, reason, affected files, retrieval embedding, and structured design context when appropriate.

## 1:50-2:28 - Show the audit trail

**Visual:** Switch to the dashboard. Show the timeline, conflict entry, and design tab. Open **Edit memory**, change one harmless word, and save.

**Say:**

> The dashboard makes the saved decisions easy to inspect. If a memory is wrong or unclear, I can edit it, and Atlas updates the retrieval data and project summary.

## 2:28-2:40 - Close

**Visual:** Dashboard overview or simple Atlas title card.

**Say:**

> Atlas gives Codex the project context that usually gets lost between sessions, and warns before old decisions are reversed by accident.

## Accuracy guardrails

- Say "project-scoped engineering memory," not "permanent memory."
- Say "retrieves relevant saved decisions," not "reads every past conversation."
- Say "an explicit MCP workflow," not "Atlas watches every Codex message."
- Do not claim measured token or billing savings; dashboard figures are estimates.
- Do not claim the product automatically edits code or blocks a developer's choice.
