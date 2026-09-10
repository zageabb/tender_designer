from __future__ import annotations

import inspect

import research_core

from services import research_core_adapter


def test_research_core_is_pinned_v02_api():
    assert research_core.__version__ == "0.2.0"
    assert hasattr(research_core, "ResearchEngine")
    assert hasattr(research_core, "DynamicResearchController")
    assert hasattr(research_core, "rank_candidates")


def test_equipment_adapter_delegates_to_shared_engine():
    source = inspect.getsource(research_core_adapter)
    assert "ResearchEngine" in source
    assert "rank_candidates" in source
    assert "Research Core: v" in source
