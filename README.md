# Tender Designer

Tender Designer is a Flask application for managing tender documents, extraction workflows, pricing, RFIs, questions, and admin corrections.

## Current Stage

This initial build includes:

- Flask app skeleton with Bootstrap layout
- SQLite database with the core tender, admin, and chat tables
- Tender CRUD screens
- Tender document upload and storage under `data/tenders/{tender_id}/...`
- Document text extraction for `pdf`, `docx`, `xlsx`, `txt`, `csv`, and `eml`
- Ollama client and extraction buttons for metadata, items, and questions
- Tender detail page with documents, items, sub-items, and questions
- Admin area with generic list/view/edit/create screens
- Persistent right-side chat panel with basic context-aware responses and upload endpoint
- Settings screen for default models and RFI text
- Manual item, sub-item, and question entry on tender detail pages
- RFI generation with downloadable `.eml` files
- Ollama-backed Computer Finder for matching a supplied machine specification to sourced brand/model recommendations from editable search websites

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

This starts the app on the network so you can connect manually from another machine at `http://SERVER_IP:5050`.

## Sample Data

To load a realistic demo dataset for screen verification:

```bash
cd tender_designer
source .venv/bin/activate
python seed_sample_data.py
```

You can also load the same dataset from the dashboard using the `Load Sample Data` button.

## Notes

- Default Ollama URL: `http://192.168.1.249:11434`
- Database file: `tender_designer.db`
- Uploaded files and extracted text are kept in `data/`
- LLM extraction output is logged in `LLMRunLog`
- Computer Finder uses Ollama for query planning and recommendations, plus site-restricted web search over domains configured in Settings or on the Computer Finder page
- For single-user server use, SQLite is still fine as long as the app is only started once.
- The recommended launch command is `flask --app app run --host=0.0.0.0 --port=5050`.

## Next Steps

- RFI generation and `.eml` export
- Supplier response parsing and confirmation workflow
- RAG document chunking and retrieval
- Richer chat action handling with validated updates
