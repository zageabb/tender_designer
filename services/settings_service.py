from __future__ import annotations

from models import AppSetting


DEFAULT_COMPUTER_FINDER_DOMAINS = "\n".join(
    [
        "dell.com",
        "hp.com",
        "lenovo.com",
        "apple.com",
        "microsoft.com",
        "asus.com",
        "acer.com",
        "cdw.com",
        "insight.com",
        "connection.com",
        "provantage.com",
        "newegg.com",
        "bestbuy.com",
    ]
)

DEFAULT_SETTINGS = {
    "ollama_url": {
        "value": "http://192.168.1.249:11434",
        "description": "Base URL for the Ollama server.",
    },
    "llm_orchestrator_model": {
        "value": "llama3.2",
        "description": "Model used for orchestration and future tool-routing decisions.",
    },
    "llm_chat_model": {
        "value": "llama3.2",
        "description": "Model used for general tender chat answers when no explicit action is being proposed.",
    },
    "llm_metadata_model": {
        "value": "llama3.2",
        "description": "Model used for tender metadata extraction.",
    },
    "llm_item_model": {
        "value": "llama3.2",
        "description": "Model used for item and sub-item extraction.",
    },
    "llm_question_model": {
        "value": "llama3.2",
        "description": "Model used for tender question extraction.",
    },
    "llm_rfq_parser_model": {
        "value": "llama3.2",
        "description": "Model used for supplier response parsing.",
    },
    "llm_rag_model": {
        "value": "llama3.2",
        "description": "Model used for answer generation with retrieved RAG context.",
    },
    "embedding_model": {
        "value": "nomic-embed-text",
        "description": "Embedding model used for future RAG indexing.",
    },
    "default_email_signature": {
        "value": "Kind regards,\nTender Designer Team",
        "description": "Default signature appended to RFQ email bodies.",
    },
    "mail_account_email": {
        "value": "abbot.server@gmail.com",
        "description": "Mailbox account address used for sending and receiving tender email.",
    },
    "mail_username": {
        "value": "abbot.server@gmail.com",
        "description": "Mailbox login username for IMAP and SMTP access.",
    },
    "mail_app_password": {
        "value": "",
        "description": "Google app password used for IMAP and SMTP access.",
    },
    "mail_from_name": {
        "value": "Tender Designer",
        "description": "Display name used when Tender Designer sends email directly.",
    },
    "mail_imap_host": {
        "value": "imap.gmail.com",
        "description": "IMAP host used to sync mailbox messages.",
    },
    "mail_imap_port": {
        "value": "993",
        "description": "IMAP SSL port used to sync mailbox messages.",
    },
    "mail_inbox_folder": {
        "value": "INBOX",
        "description": "Mailbox folder to sync into Tender Designer.",
    },
    "mail_sync_limit": {
        "value": "20",
        "description": "Maximum number of recent mailbox messages to sync per request.",
    },
    "mail_smtp_host": {
        "value": "smtp.gmail.com",
        "description": "SMTP host used to send Tender Designer email directly.",
    },
    "mail_smtp_port": {
        "value": "587",
        "description": "SMTP port used to send Tender Designer email directly.",
    },
    "mail_use_starttls": {
        "value": "true",
        "description": "Use STARTTLS for SMTP connections when sending directly.",
    },
    "vector_store_path": {
        "value": "data/vector_store",
        "description": "Local vector store path for future RAG support.",
    },
    "computer_finder_model": {
        "value": "llama3.2",
        "description": "Ollama model used to plan searches and recommend a computer from sourced web results.",
    },
    "computer_finder_searxng_url": {
        "value": "http://192.168.1.249:8081",
        "description": "Optional SearXNG base URL used as the primary web search provider for Computer Finder.",
    },
    "computer_finder_searxng_engines": {
        "value": "google,bing",
        "description": "Optional comma-separated SearXNG engines for Computer Finder searches. Leave blank to use SearXNG defaults.",
    },
    "computer_finder_results_per_domain": {
        "value": "3",
        "description": "Maximum site-restricted search results to collect from each configured website.",
    },
    "computer_finder_max_pages_to_read": {
        "value": "8",
        "description": "Maximum candidate web pages to fetch and summarise before asking Ollama for a recommendation.",
    },
    "computer_finder_allowed_domains": {
        "value": DEFAULT_COMPUTER_FINDER_DOMAINS,
        "description": "One searchable website domain per line for computer finder results. Omit https:// prefixes.",
    },
    "computer_finder_blocked_domains": {
        "value": "reddit.com\nquora.com\nwikipedia.org",
        "description": "Optional website domains to exclude from computer finder web searches.",
    },
    "computer_finder_market_country": {
        "value": "US",
        "description": "Default procurement country for computer finder searches, using a two-letter country code.",
    },
    "computer_finder_market_region": {
        "value": "",
        "description": "Optional state, province, or region used to localise computer finder searches.",
    },
    "computer_finder_market_city": {
        "value": "",
        "description": "Optional city used to localise computer finder searches.",
    },
}

TASK_MODEL_SETTING_KEYS = {
    "orchestrator": "llm_orchestrator_model",
    "chat_answering": "llm_chat_model",
    "metadata_extraction": "llm_metadata_model",
    "item_extraction": "llm_item_model",
    "question_extraction": "llm_question_model",
    "rfq_response_parser": "llm_rfq_parser_model",
    "rag_answering": "llm_rag_model",
}


def ensure_default_settings(db) -> None:
    existing_keys = {setting.key for setting in AppSetting.query.all()}
    changed = False
    for key, payload in DEFAULT_SETTINGS.items():
        if key not in existing_keys:
            db.session.add(
                AppSetting(
                    key=key,
                    value=payload["value"],
                    description=payload["description"],
                )
            )
            changed = True
    if changed:
        db.session.commit()


def get_setting(key: str, fallback: str | None = None) -> str | None:
    setting = AppSetting.query.filter_by(key=key).first()
    if setting is not None and setting.value is not None:
        return setting.value
    default = DEFAULT_SETTINGS.get(key)
    if default is not None:
        return default["value"]
    return fallback


def get_task_model(task_name: str, fallback: str | None = None) -> str | None:
    setting_key = TASK_MODEL_SETTING_KEYS.get(task_name)
    if setting_key is None:
        return fallback
    return get_setting(setting_key, fallback)
