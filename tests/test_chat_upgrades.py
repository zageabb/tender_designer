from types import SimpleNamespace

from services.chat_document_service import build_chat_document
from services.markdown_tools import render_markdown_html
from services.tender_knowledge import build_tender_knowledge_context


def test_markdown_renderer_supports_tables_and_sanitizes_script():
    rendered = str(
        render_markdown_html(
            "# Result\n\n| Item | Value |\n| --- | --- |\n| A | **Yes** |\n\n<script>alert('x')</script>"
        )
    )
    assert "<table" in rendered
    assert "<strong>Yes</strong>" in rendered
    assert "<script" not in rendered
    assert "alert(" not in rendered


def test_tender_knowledge_uses_all_processed_documents_and_ranks_relevance():
    tender = SimpleNamespace(
        documents=[
            SimpleNamespace(
                original_filename="technical_spec.md",
                extracted_text="Transformer requirement: 400 kV GIS interface and 2000 A continuous current.",
            ),
            SimpleNamespace(
                original_filename="commercial_terms.md",
                extracted_text="Commercial terms include a three year warranty and delivery schedule.",
            ),
        ]
    )
    context, sources = build_tender_knowledge_context(tender, "What is the required current and warranty?")
    assert "technical_spec.md" in context
    assert "commercial_terms.md" in context
    assert len(sources) == 2
    assert "2000 A" in context
    assert "three year warranty" in context


def test_chat_document_builder_returns_docx_bytes():
    content = build_chat_document(
        "Compliance Summary",
        "# Compliance Summary\n\n- Requirement one\n- Requirement two\n\n## Notes\nEvidence-backed draft.",
    )
    assert content[:2] == b"PK"
    assert len(content) > 500
