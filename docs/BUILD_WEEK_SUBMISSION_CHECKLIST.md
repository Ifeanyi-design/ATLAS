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
- [x] Compiled `packaging/windows/Output/AtlasSetup.exe` with Inno Setup.
- [ ] Publish `AtlasSetup.exe` as a GitHub Release asset so judges can download it without rebuilding. Do not include `.env`, databases, or API keys.
- [ ] Commit `docs/DEMO_SCRIPT.md` and keep it aligned with the recorded demo.

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
- The compiled EXE exists locally. Remaining delivery work: publish it as a GitHub Release asset, record/upload the public YouTube demo, fill Devpost fields, and capture the `/feedback` session ID.
