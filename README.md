# Tender Designer

Tender Designer is a Flask application for managing tenders, uploaded documents, AI-assisted extraction, questions and answers, RFI email drafting, mailbox workflows, and admin correction screens.

## What The App Does

- Creates and edits tenders, items, sub-items, questions, documents, RFIs, and tender email drafts
- Uploads and stores tender files under `data/tenders/{tender_id}/...`
- Extracts text from `pdf`, `docx`, `xlsx`, `csv`, `txt`, `md`, `eml`, and `msg`
- Expands uploaded `.zip` files and stores the extracted files as normal tender documents
- Stores extracted document text in markdown when possible and renders markdown across the UI
- Runs background AI jobs for metadata extraction, item extraction, question extraction, and question answer drafting
- Logs AI activity into the tender chat so users can see prompts, breadcrumbs, and progress
- Lets users select specific tender documents before extraction or AI chat context is built
- Creates RFI `.eml` drafts from selected tender items and sub-items
- Creates tender document email drafts with real file attachments from selected tender documents
- Supports direct send for generated email drafts through a configured Gmail account
- Syncs mailbox email into the app, shows folders, supports multi-select actions, and can create a tender from an email
- Imports mailbox attachments into tenders automatically when a tender is created or linked from email
- Includes a Computer Finder workflow that uses Ollama plus web search over editable supplier domains
- Includes a generic admin area for viewing and editing all major tables

## Current Architecture

- Flask app with Bootstrap-based templates
- SQLite database in `tender_designer.db`
- Local file repository in `data/`
- Ollama-backed task execution for extraction, orchestration, chat, and computer finder flows
- Background extraction worker for tender AI jobs
- Background mailbox sync worker for Gmail sync requests
- Prompt and template library stored as individual markdown files in `llm_prompts/`

## Setup

```bash
cd tender_designer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --host=0.0.0.0 --port=5050
```

Or use the included launcher:

```bash
cd tender_designer
./start_tender_designer.sh
```

## Network / Server Use

The app is configured to run on port `5050` and is intended to be reachable across your local network.

- Launch with `--host=0.0.0.0` so other devices can connect
- No browser is opened automatically in the server-oriented launcher flow
- Connect manually from another machine using `http://SERVER_IP:5050`
- For the current single-user setup, SQLite is acceptable as long as only one Tender Designer process is writing to the database

## Background Workers

Tender Designer starts two in-process background workers when the app boots:

- Extraction worker: handles metadata, item, question, and answer-drafting jobs
- Mailbox sync worker: handles Gmail sync jobs

Recent behavior:

- Extraction jobs queue immediately and continue while users navigate elsewhere
- Mailbox sync now returns the UI quickly and continues in the background
- The extraction worker now self-recovers if the thread dies and will restart when new work is queued or the worker is resumed from Admin

Admin screens show worker state, queued jobs, and recent job history.

## Supported Document Inputs

Tender document upload and chat-upload workflows currently support:

- `pdf`
- `docx`
- `xlsx`
- `csv`
- `txt`
- `md`
- `eml`
- `msg`
- `zip`

Notes:

- `.zip` uploads are expanded and each contained file is stored individually
- `.msg` extraction requires the `extract-msg` package to be installed
- Existing uploaded files can be replaced by re-uploading with the same effective destination

## Gmail / Mailbox Setup

Tender Designer supports Gmail-based sending and receiving using an app password.

Relevant Settings keys:

- `mail_account_email`
- `mail_username`
- `mail_app_password`
- `mail_from_name`
- `mail_imap_host`
- `mail_imap_port`
- `mail_inbox_folder`
- `mail_sync_limit`
- `mail_smtp_host`
- `mail_smtp_port`
- `mail_use_starttls`

Current behavior:

- Inbox sync pulls the full `INBOX` history
- Other folders still respect `mail_sync_limit`
- Mailbox deletions are also synced back toward Gmail
- Mailbox sync jobs and deletion requests are visible in Admin

## AI / Ollama Settings

Important defaults are stored in Settings and can be edited in the UI:

- `ollama_url`
- `llm_orchestrator_model`
- `llm_chat_model`
- `llm_metadata_model`
- `llm_item_model`
- `llm_question_model`
- `llm_rfq_parser_model`
- `llm_rag_model`
- `computer_finder_model`

Prompt instructions for each AI task are stored as individual markdown files in `llm_prompts/` and are editable from the Settings screen.

## Sample Data

To load a realistic demo dataset for screen verification:

```bash
cd tender_designer
source .venv/bin/activate
python seed_sample_data.py
```

You can also load the same dataset from the dashboard using the `Load Sample Data` button.

## Key Data Locations

- Database: `tender_designer.db`
- Tender files and extracted text: `data/`
- Prompt/template library: `llm_prompts/`

## Useful Screens

- Dashboard: overall tender summary and sample-data entry point
- Tender detail: documents, items, sub-items, questions, jobs, RFI drafts, tender email drafts, mailbox links
- Mailbox: synced Gmail messages, folders, bulk actions, and tender creation/import flow
- Settings: models, mailbox settings, email defaults, and editable markdown prompt/template files
- Admin: editable table views plus extraction and mailbox job visibility

## Template And Prompt Reference

See [TEMPLATE_FIELDS_README.md](/Users/geraldabbot/Documents/Codex/2026-06-26/ini/tender_designer/TEMPLATE_FIELDS_README.md) for the placeholder fields supported by the markdown prompt and email template files.
