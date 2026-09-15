from flask import Flask

import services.computer_finder_jobs as computer_finder_jobs
from services.agentic_web_search import SearchResult
from services.enhanced_equipment_reader import (
    _evidence_sufficient,
    _structured_product_text,
)
from services.equipment_research_agent import EquipmentResearchAgent
from services.settings_service import DEFAULT_SETTINGS


def test_structured_product_metadata_extracts_identity_and_ratings():
    html = '''
    <html><head>
      <script type="application/ld+json">
      {
        "@type": "Product",
        "name": "Example NX 12",
        "model": "NX-12-3150",
        "mpn": "NX123150",
        "brand": {"@type": "Brand", "name": "Example Energy"},
        "additionalProperty": [
          {"@type": "PropertyValue", "name": "Rated voltage", "value": "12 kV"},
          {"@type": "PropertyValue", "name": "Rated current", "value": "3150 A"},
          {"@type": "PropertyValue", "name": "Short-circuit rating", "value": "31.5 kA"}
        ]
      }
      </script>
    </head><body></body></html>
    '''

    text = _structured_product_text(html)

    assert "Example NX 12" in text
    assert "NX-12-3150" in text
    assert "Example Energy" in text
    assert "Rated voltage: 12 kV" in text
    assert "Rated current: 3150 A" in text
    assert "Short-circuit rating: 31.5 kA" in text


def test_evidence_sufficiency_is_based_on_technical_content_not_price():
    technical = (
        "Manufacturer technical datasheet. Model NX-12. Rated voltage 12 kV. "
        "Rated current 3150 A. Short-circuit rating 31.5 kA. IEC 62271-200. "
        + "Technical specification details. " * 40
    )
    commercial_only = "Price £12,500 available now. Buy online. " * 40

    assert _evidence_sufficient(technical) is True
    assert _evidence_sufficient(commercial_only) is False


def test_equipment_candidate_ranking_prefers_matching_datasheet(monkeypatch):
    monkeypatch.setattr("services.equipment_research_agent.get_setting", lambda *args, **kwargs: "")
    agent = EquipmentResearchAgent(
        ollama_url="http://127.0.0.1:11434",
        model="test-model",
        search_provider=None,
        page_reader=None,
        allowed_domains=[],
        blocked_domains=[],
    )
    candidates = [
        SearchResult(
            title="Generic switchgear accessories and spare parts",
            url="https://example.com/accessories",
            snippet="Accessories for medium-voltage equipment.",
            query="12 kV 3150 A switchgear",
        ),
        SearchResult(
            title="NX-12 switchgear technical datasheet PDF",
            url="https://manufacturer.example/NX-12-datasheet.pdf",
            snippet="Rated voltage 12 kV, rated current 3150 A, short-circuit rating 31.5 kA, IEC 62271-200.",
            query="12 kV 3150 A 31.5 kA IEC 62271-200 switchgear datasheet",
        ),
    ]

    ranked, diagnostics = agent._rank_candidates(
        candidates,
        "12 kV switchgear, 3150 A, 31.5 kA, IEC 62271-200",
        {"mandatory": "12 kV; 3150 A; 31.5 kA; IEC 62271-200"},
        ["Which exact model proves all mandatory ratings?"],
    )

    assert ranked[0].url.endswith("NX-12-datasheet.pdf")
    assert any("Ranked 2 candidate" in row for row in diagnostics)


def test_dynamic_equipment_research_defaults_are_quality_led():
    assert DEFAULT_SETTINGS["equipment_research_depth_mode"]["value"] == "auto"
    assert int(DEFAULT_SETTINGS["equipment_research_initial_pages"]["value"]) < int(
        DEFAULT_SETTINGS["equipment_research_hard_page_cap"]["value"]
    )
    assert int(DEFAULT_SETTINGS["equipment_research_hard_page_cap"]["value"]) > 100


def test_vendor_knowledge_only_mode_can_be_requested_by_marker_or_plain_language():
    assert computer_finder_jobs._vendor_only_requested(
        "Need a laptop\n[VENDOR_KNOWLEDGE_ONLY]", "computer"
    ) is True
    assert computer_finder_jobs._vendor_only_requested(
        "Only use Vendor Knowledge for this tender", "computer"
    ) is True
    assert computer_finder_jobs._vendor_only_requested(
        "Only use Vendor Knowledge for this tender", "general"
    ) is False
    assert computer_finder_jobs._strip_vendor_only_marker(
        "Need a laptop\n[VENDOR_KNOWLEDGE_ONLY]"
    ) == "Need a laptop"


def test_vendor_knowledge_only_mode_skips_web_discovery_when_no_vendor_candidates(monkeypatch):
    app = Flask(__name__)
    job_id = "vendor-only-no-match"
    computer_finder_jobs._jobs[job_id] = {"events": [], "status": "queued"}
    monkeypatch.setattr(computer_finder_jobs, "install_research_core_equipment", lambda: None)
    monkeypatch.setattr(computer_finder_jobs, "build_vendor_search_context", lambda *args, **kwargs: ("", 0))

    def fail_if_web_search_runs(*args, **kwargs):
        raise AssertionError("Web product discovery should not run without a Vendor Knowledge candidate")

    monkeypatch.setattr(computer_finder_jobs, "find_computer_for_spec", fail_if_web_search_runs)
    try:
        computer_finder_jobs._run_job(
            app,
            job_id,
            "Need a 14 inch business laptop\n[VENDOR_KNOWLEDGE_ONLY]",
            "computer",
            False,
            None,
        )
        job = computer_finder_jobs._jobs[job_id]
        assert job["status"] == "completed"
        assert "no currently active and available Vendor Knowledge products matched" in job["message"]
        assert "no internet product discovery was performed" in job["message"].lower()
    finally:
        computer_finder_jobs._jobs.pop(job_id, None)


def test_vendor_knowledge_only_mode_uses_web_only_to_verify_closed_candidate_set(monkeypatch):
    app = Flask(__name__)
    job_id = "vendor-only-with-match"
    computer_finder_jobs._jobs[job_id] = {"events": [], "status": "queued"}
    monkeypatch.setattr(computer_finder_jobs, "install_research_core_equipment", lambda: None)
    monkeypatch.setattr(
        computer_finder_jobs,
        "build_vendor_search_context",
        lambda *args, **kwargs: ("VK1: Vendor=Example | Description=ExampleBook 14 | PartNo=EX14-16-512 | Qty=10", 1),
    )
    captured = {}

    def fake_research(spec, **kwargs):
        captured["spec"] = spec
        return {"answer": "Verified Vendor Knowledge candidate.", "sources": [], "steps": []}

    monkeypatch.setattr(computer_finder_jobs, "find_computer_for_spec", fake_research)
    try:
        computer_finder_jobs._run_job(
            app,
            job_id,
            "14 inch, 16 GB RAM, 512 GB SSD\n[VENDOR_KNOWLEDGE_ONLY]",
            "computer",
            False,
            None,
        )
        assert "VENDOR KNOWLEDGE CANDIDATES ONLY MODE" in captured["spec"]
        assert "Only products listed in the Vendor Knowledge section below may appear in the answer" in captured["spec"]
        assert "Do NOT discover, recommend, compare or mention alternative products" in captured["spec"]
        assert computer_finder_jobs._jobs[job_id]["status"] == "completed"
    finally:
        computer_finder_jobs._jobs.pop(job_id, None)
