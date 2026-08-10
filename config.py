from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'tender_designer.db'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"connect_args": {"check_same_thread": False, "timeout": 30}}
        if SQLALCHEMY_DATABASE_URI.startswith("sqlite:")
        else {}
    )
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    DATA_DIR = Path(os.environ.get("DATA_DIR", DATA_DIR))
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
    PRODUCTION_MODE = os.environ.get("TENDER_DESIGNER_PRODUCTION", "").lower() in {"1", "true", "yes"}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://192.168.1.249:11434")
    LLM_MODELS = {
        "orchestrator": os.environ.get("LLM_ORCHESTRATOR_MODEL", "llama3.2"),
        "chat_answering": os.environ.get("LLM_CHAT_MODEL", "llama3.2"),
        "metadata_extraction": os.environ.get("LLM_METADATA_MODEL", "llama3.2"),
        "item_extraction": os.environ.get("LLM_ITEM_MODEL", "llama3.2"),
        "question_extraction": os.environ.get("LLM_QUESTION_MODEL", "llama3.2"),
        "rfq_response_parser": os.environ.get("LLM_RFQ_PARSER_MODEL", "llama3.2"),
        "rag_answering": os.environ.get("LLM_RAG_MODEL", "llama3.2"),
    }
    ALLOWED_UPLOAD_EXTENSIONS = {
        ".pdf",
        ".docx",
        ".xlsx",
        ".txt",
        ".md",
        ".eml",
        ".msg",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".avif",
        ".zip",
    }
