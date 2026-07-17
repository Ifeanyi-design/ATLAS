# Atlas Build Week Submission Checklist

## Required submission material

- [ ] Select **Developer Tools** as the single track.
- [ ] Write the project description: problem, solution, key workflow, and why it matters.
- [ ] Upload a **public YouTube** demo video that is under 3 minutes, includes audio, shows the product working, and explains how Codex and GPT-5.6 were used.
- [ ] Provide the code repository URL.
- [ ] Make the repository public with a license, or share a private repository with `testing@devpost.com` and `build-week-event@openai.com`.
- [ ] Include the primary build thread's Codex `/feedback` session ID in the Devpost form. Do not commit it to the repository.

## Developer-tool judge path

- [ ] README has setup, supported-platform, and test instructions.
- [ ] Include a simple way for judges to test Atlas without rebuilding from scratch. The preferred final form is a compiled `AtlasSetup.exe` plus the existing SQLite path.
- [ ] Compile and attach/release the installer only after Inno Setup is available; do not include `.env`, databases, or API keys.
- [ ] Keep `docs/DEMO_SCRIPT.md` aligned with the recorded demo.

## Final proof before upload

- [ ] Fresh Codex task in a separate project retrieves the correct Atlas project memory.
- [ ] Demonstrate a conflict warning, a new logged decision, dashboard display, and one memory edit.
- [ ] Run `atlas doctor` with no failures.
- [ ] Run the test suite and record the final passing count in `docs/PROGRESS.md`.
- [ ] Capture evidence that Codex/GPT-5.6 was used during the submission period: the primary thread, relevant session history, and/or commits.

## Current project status (2026-07-17)

- Tests: 37 passed.
- Global Atlas install and `atlas attach` work.
- SQLite setup, dashboard, memory edits, optional PIN, and MCP tools are implemented.
- The final live end-to-end recording and compiled EXE installer remain to be completed.
