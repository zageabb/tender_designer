# Tender Designer Upgrade Plan

This is the implementation checklist produced from the 28 July 2026 full-code review.
An item is marked complete only after its code and relevant verification pass.

## Critical security

- [x] Add authentication and protect every application route except login and static assets.
- [x] Add role-aware administration boundaries.
- [x] Add CSRF protection to HTML forms and JSON mutations.
- [x] Require secure production configuration for the Flask secret and administrator credentials.
- [x] Add secure session-cookie defaults.
- [x] Prevent editable database paths from enabling arbitrary file reads or deletion.
- [x] Store and resolve managed files only beneath the configured data directory.

## High-priority reliability and input safety

- [x] Prevent duplicate background workers and schedulers across WSGI processes.
- [x] Add database-backed worker ownership/lease protection.
- [x] Validate every Computer Finder redirect before following it.
- [x] Limit downloaded Computer Finder response sizes.
- [x] Add ZIP member-count, expanded-size, total-size, and compression-ratio limits.

## Search quality and observability

- [x] Preserve structured search and page-reading diagnostics instead of swallowing exceptions.
- [x] Treat webpage content as untrusted data in Ollama prompts.
- [x] Validate final citation identifiers against collected evidence.
- [x] Run independent search queries concurrently.
- [x] Add a bounded in-memory search-result cache.

## Secrets, persistence, and maintainability

- [x] Move mailbox credentials to environment-backed secrets.
- [x] Mask secret settings and exclude them from generic Admin browsing/editing.
- [x] Introduce Alembic/Flask-Migrate for versioned schema changes.
- [x] Make database engine options conditional on the selected database backend.
- [x] Remove obsolete SearXNG settings, helpers, and browser context code.

## Automated verification

- [x] Add committed tests for authentication and CSRF.
- [x] Add committed tests for managed file paths and ZIP limits.
- [x] Add committed tests for worker ownership.
- [x] Add committed tests for Computer Finder redirect safety, diagnostics, prompt isolation, caching, response limits, and citations.
- [x] Run Python compilation, JavaScript syntax, dependency, Flask smoke, migration, and automated test checks.

## Deployment notes

Required production environment:

```bash
export TENDER_DESIGNER_PRODUCTION=true
export SECRET_KEY="<long-random-secret>"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="<strong-password>"
export MAIL_APP_PASSWORD="<mail-provider-app-password>"
export SESSION_COOKIE_SECURE=true  # when served over HTTPS
```

`ADMIN_PASSWORD_HASH` may be used instead of `ADMIN_PASSWORD`.

For an existing database, record the new migration baseline after pulling this upgrade:

```bash
flask --app app db stamp 39d988e8d221
```

For a new empty database:

```bash
TENDER_DESIGNER_MIGRATION_MODE=true flask --app app db upgrade
```

Then restart Tender Designer. The application retains the additive legacy bootstrap temporarily so
existing installations remain recoverable while migration ownership is introduced.
