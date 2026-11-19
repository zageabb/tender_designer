# UDA V2 candidate — Tender Designer (DEV-020)

**State: REVIEW ONLY. No install, migration, rollback, proxy change or automatic update is authorised.**

## Source evidence

- Web entrypoint: `start_tender_designer.sh`, invoking Flask `app` on port 5050.
- Mailbox entrypoint: `start_mailbox_service.sh`, invoking `mailbox_daemon.py`,
  which explicitly sets `TENDER_DESIGNER_PROCESS_ROLE=mailbox`.
- The web app starts extraction, monitor and scheduler workers inside the web process;
  the standalone mailbox daemon has a separate database-backed lease.
- Existing mailbox systemd example:
  `ollama-chat-tender-designer-mailbox.service`, using protected environment
  `%h/.config/ollama-chat/tender-designer.env`. Treat this as an **example**,
  not evidence of current effective host state.
- Source default persistence: `tender_designer.db` and `data/` under checkout;
  editable prompt library `llm_prompts/`. These require preservation/backup
  and path ownership review before any release replacement.
- Existing Alembic guidance includes `flask db stamp` for legacy upgrades.
  V2 must NOT run any migration or stamping command until database revision,
  backup and idempotency have been independently verified.
- The web and mailbox launchers require local `.venv`; the candidate's
  Python build creates it. Its external research-core Git dependency will
  require a reviewed isolated network-capable build environment.
- Authentication is both in-app (Flask login) and through UDA proxy.
  Validate login redirect, forwarded-prefix behaviour, CSRF and cookie scope
  in the authorised Desktop acceptance stage.

## Required read-only host reconciliation on m901-lenovo

- [ ] Compare real effective web and mailbox systemd units and working dirs;
      do not assume example unit names for lifecycle ownership.
- [ ] Compare actual web port, loopback exposure, URL and Caddy auth/prefix.
- [ ] Confirm required production secret **names only** and whether admin auth
      uses `ADMIN_PASSWORD` or `ADMIN_PASSWORD_HASH`; do not copy values.
      Candidate currently assumes `ADMIN_PASSWORD_HASH` and must be amended
      if real host configuration differs.
- [ ] Confirm `TENDER_DESIGNER_PRODUCTION`, mailbox service policy and the
      inherited protected EnvironmentFile. Avoid duplicating mailbox schedulers.
- [ ] Locate and preserve SQLite database, WAL/journal, `data/` attachments
      and mutable prompts; obtain an independent backup/restore plan.
- [ ] Confirm build isolation/network dependency permissions.
- [ ] Confirm web and mailbox health checks provide meaningful acceptance:
      HTTP login verifies web only; process probe does not prove IMAP sync.
- [ ] Verify that legacy app group in the UDA registry matches the declared
      review group (do not silently change access).
- [ ] Only after the above: schema + semantic validator in UDA workspace,
      isolated source tests, Desktop read-only comparison, explicit owner sign-off.

## Suggested independent schema/semantic checks

From a disposable UDA development checkout with the V2 validator and
`jsonschema`/`PyYAML` installed, point this test at the candidate file:

```bash
python - <<'PY'
import yaml
from uda_manifest_v2_validate import validate
with open('/path/to/tender_designer/uda.v2.yaml', encoding='utf-8') as f:
    manifest = yaml.safe_load(f)
print(validate(manifest))
PY
```

A successful validation proves only the manifest's schema/graph consistency;
it does not authorize starting the web, mailbox worker or schema migrations.
