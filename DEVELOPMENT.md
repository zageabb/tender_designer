# Development Status

Last reviewed: 2026-10-13
Current development state: ACTIVE

## Purpose
Common development ledger for the user and AI agents. Existing project-specific planning documents remain valid; this file standardises status and completion evidence.

## Current objective
Tender-specific knowledge, richer LLM chat/tools, mailbox service and document-building workflows.

## Existing planning and evidence sources
- `README.md`
- `UPGRADE.md`
- `EQUIPMENT_RESEARCH.md`
- `TENDER_SIGNAL_MATRIX.md`
- `tests/`
- `GitHub Actions`

## Status values
- 🔵 PLANNED
- 🔨 IN PROGRESS
- 🚫 BLOCKED
- ⏳ AWAITING ACCEPTANCE
- ✅ COMPLETE
- 💤 DEFERRED

## Evidence standard
An item is COMPLETE only when applicable repository evidence verifies it: implementation, changed files/non-empty diff, tests or recorded no-test reason, passing tests, CI where available, commit/PR evidence, intended-branch merge, and separately recorded external/user acceptance.

For coding work, an empty result, no write/edit action, unchanged branch HEAD, empty diff or missing requested validation means the task is not complete.

## Development ledger

### DEV-001 — Make AI metadata extraction resilient to duplicate tender numbers
Status: ⏳ AWAITING ACCEPTANCE
Priority: High
Owner/Agent: Codex
Branch: main
Depends on: None
Can run in parallel with: Unrelated tender workflows
Integration status: deployed to the Ubuntu service

Requirement: AI metadata extraction must not fail when a document contains a tender number already assigned to another tender, background-worker error handling must recover a failed SQLAlchemy transaction before recording the job failure, and repeated mailbox intake must not create another tender for an already-linked email.

Implementation: Metadata extraction preserves the current tender number when the extracted number is already in use and reports the conflict in the completed job summary. The extraction worker explicitly rolls back before querying and updating a failed job. Mailbox tender creation now reopens the first linked tender instead of creating a duplicate.

Evidence:
- Files: `services/llm_tasks.py`, `services/extraction_jobs.py`, `services/mailbox_service.py`, `routes/mailbox.py`, `tests/test_extraction_jobs.py`
- Tests: `pytest -q tests/test_extraction_jobs.py` (3 passed); `pytest -q` (64 passed).
- CI: pending.
- Deployment: commit `865bb46` deployed to `/home/zageabb/ollama-chat/Tender_Designer`; focused production-environment tests passed (2 tests).
- Production verification: the durable source tender is tender 61 with tender number `182`; its metadata, items, and questions are complete. The failed tender 62 was a transient duplicate of the same mailbox message and was not restored after service restart.
- User/business acceptance: pending.

Completion criteria:
- [x] Duplicate extracted tender numbers no longer poison the worker transaction.
- [x] Worker failure recording rolls back before querying the job.
- [x] Repeated mailbox intake reuses the existing linked tender.
- [x] Relevant tests pass.
- [x] Change is deployed and the production duplicate-number condition is verified.
- [ ] User acceptance is recorded separately.

### OPS-UDA-002 — Prevent duplicated prefix on research API requests
Status: ✅ COMPLETE

Issue: Equipment Research succeeded on the LAN but returned a Flask HTML 404 through UDA/Caddy. Flask-generated `url_for` routes already contained `/apps/tender-designer`, and the global fetch wrapper duplicated that prefix.

Implementation: `templates/base.html` now detects already-prefixed root-relative URLs and preserves them, while continuing to scope legacy root-relative URLs. This retains LAN behaviour. Fix merged directly to `main` in commit `9b0f99ba`, documented in `ca6c0bdc`.

Evidence: existing `tests/test_uda_subpath.py` covers UDA prefix URL rendering; source inspection verified the corrected client URL handling. On 2026-10-13, user reported the reverse-proxy Equipment Research search was running after deployment and explicitly accepted closure. GitHub combined commit status query returned no CI statuses; a fresh CI pass and final result completion were not independently verified, so these are not claimed.

- [x] Fix duplicate prefix handling on `main`
- [x] User verified research search starts through the reverse proxy
- [x] User accepted issue closure (2026-10-13)

### OPS-UDA-001 — Trusted UDA path-prefixed deployment
Status: ⏳ AWAITING ACCEPTANCE

Scope: live registered Tender Designer application only.
Implementation: one-hop ProxyFix, prefix-safe Flask URLs and shared template `<base>`; existing CSRF-aware fetch wrapper now scopes root-relative same-origin API calls to the application's prefix. The application uses a unique session-cookie name and dynamically scopes the cookie to `/` on LAN or `/apps/tender-designer/` through UDA. LAN root access remains unchanged.
Security: keep UDA/Caddy the only trusted forwarding ingress, preserve CSRF/auth and do not enable public proxy before acceptance.
Evidence: `tests/test_uda_subpath.py`; focused proxy test 1 passed; complete suite 61 passed; existing GitHub Actions full pytest workflow.

- [ ] CI green and PR merged to `main`
- [ ] Verify UDA auth, tender creation/upload, chat, document downloads and background jobs in browser



### DEV-000 — Establish evidence-based development ledger
Status: ✅ COMPLETE

Evidence:
- Files: `DEVELOPMENT.md`, `AGENTS.md`
- Git history records these changes.
- Tests: not required for this documentation/process-only change.
- User acceptance: requested 2026-10-02.

## New item template

### DEV-XXX — Short title
Status: 🔵 PLANNED
Priority: Medium
Owner/Agent:
Branch:
Depends on:
Can run in parallel with:
Integration status:

Requirement:

Implementation:

Evidence:
- Commit:
- PR:
- Files:
- Tests:
- CI:
- Merged to intended branch:
- User/business acceptance:

Completion criteria:
- [ ] Implementation exists.
- [ ] Relevant files changed.
- [ ] Tests added/updated, or reason recorded.
- [ ] Relevant tests pass.
- [ ] CI passes where applicable.
- [ ] Commit/PR evidence recorded.
- [ ] Merged where required.
- [ ] External/user acceptance separated from development completion.

Notes:

## Parallel development coordination

Use the coordination fields on every active DEV item when parallel work is possible.

- **Owner/Agent** — the person or AI agent currently responsible for the item.
- **Branch** — the working branch or worktree used for the item.
- **Depends on** — DEV items, decisions or external prerequisites that must complete first.
- **Can run in parallel with** — DEV items that are safe to develop concurrently without conflicting ownership or sequencing.
- **Integration status** — for example: not started, isolated, ready for integration, integrated, or integration blocked.

Before starting parallel work, agents should check these fields and avoid claiming the same item, branch or overlapping integration responsibility. If two items touch the same subsystem or files, record the conflict explicitly and sequence or coordinate integration rather than assuming they are independent.

Parallel execution does not weaken the completion standard: each DEV item still requires its own implementation, tests/validation, CI evidence where applicable, and integration/merge evidence before it can be marked COMPLETE.

## Maintenance rule
Update this file during the same development pass that changes implementation. Repository evidence wins when prose disagrees.
