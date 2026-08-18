import json
from pathlib import Path
from unittest.mock import patch

from src.agents.asset_ranker import RANKING_VERSION
from src.agents.transmission_builder import MIN_CASE_SUPPORT_FOR_SECOND_ORDER, build_transmission_chain
from src.config import USE_MECHANISM_COMPATIBLE_SUPPORT
from src.pipeline import run_pipeline, run_v4_pipeline
from src.schemas import EventAnalysis, RetrievedCase
from src.v4_config import V4_CONFIG, assert_v4_config


def test_v4_config_is_frozen_at_top_k_10():
    assert V4_CONFIG.retrieval_top_k == 10
    assert V4_CONFIG.use_mechanism_compatible_support is True
    assert V4_CONFIG.compatible_support_threshold == 2
    assert V4_CONFIG.transmission_context_version == "transmission_context_v1"
    assert V4_CONFIG.canonical_family_version == "canonical_family_v1"
    assert V4_CONFIG.mechanism_compatibility_version == "mechanism_compatibility_candidate_v1"
    assert V4_CONFIG.asset_ranker_version == RANKING_VERSION
    assert_v4_config()


def test_v4_path_ignores_legacy_pipeline_default_top_k(monkeypatch):
    observed = {}
    event = _event()

    def fake_retrieve(news_text, event_arg, top_k=5):
        observed["top_k"] = top_k
        return []

    monkeypatch.setattr("src.pipeline._analyze_event", lambda news, analyzer: event)
    monkeypatch.setattr("src.pipeline.retrieve_cases", fake_retrieve)
    monkeypatch.setattr("src.pipeline.map_assets", lambda event_arg, chain: [])

    run_v4_pipeline("Red Sea shipping disruption", event_analyzer="rule")

    assert observed["top_k"] == 10


def test_legacy_path_still_uses_legacy_default_when_not_overridden(monkeypatch):
    observed = {}
    event = _event()

    def fake_retrieve(news_text, event_arg, top_k=5):
        observed["top_k"] = top_k
        return []

    monkeypatch.setattr("src.pipeline._analyze_event", lambda news, analyzer: event)
    monkeypatch.setattr("src.pipeline.retrieve_cases", fake_retrieve)
    monkeypatch.setattr("src.pipeline.map_assets", lambda event_arg, chain: [])

    run_pipeline("Red Sea shipping disruption", event_analyzer="rule")

    assert observed["top_k"] == 3


def test_v4_path_enables_mechanism_support_independent_of_env_default(monkeypatch):
    observed = {}
    event = _event()

    def fake_build(event_arg, retrieved_cases, *, use_mechanism_compatible_support=None):
        observed["support_flag"] = use_mechanism_compatible_support
        return build_transmission_chain(
            event_arg,
            retrieved_cases,
            use_mechanism_compatible_support=False,
        )

    monkeypatch.setattr("src.pipeline._analyze_event", lambda news, analyzer: event)
    monkeypatch.setattr("src.pipeline.retrieve_cases", lambda news, event_arg, top_k=5: [])
    monkeypatch.setattr("src.pipeline.build_transmission_chain", fake_build)
    monkeypatch.setattr("src.pipeline.map_assets", lambda event_arg, chain: [])

    assert USE_MECHANISM_COMPATIBLE_SUPPORT is False
    run_v4_pipeline("Red Sea shipping disruption", event_analyzer="rule")

    assert observed["support_flag"] is True


def test_vector_store_receives_v4_top_k_through_retriever(monkeypatch):
    from src.agents.case_retriever import retrieve_cases

    observed = {}

    def fake_query(query_text, top_k=5):
        observed["top_k"] = top_k
        return []

    monkeypatch.setattr("src.agents.case_retriever.query_cases", fake_query)

    retrieve_cases("news", _event(), top_k=V4_CONFIG.retrieval_top_k)

    assert observed["top_k"] == 10


def test_v4_trace_artifact_confirms_end_to_end_top_k():
    trace = json.loads(Path("data/topk_sensitivity_v4/v4_config_trace.json").read_text())

    assert trace["resolved_top_k"] == 10
    assert trace["retriever_top_k"] == 10
    assert trace["vector_store_top_k"] == 10
    assert trace["mechanism_support_enabled"] is True
    assert trace["trace_passed"] is True


def test_final_manifest_records_frozen_specification():
    manifest = json.loads(Path("data/topk_sensitivity_v4/v4_final_freeze_manifest.json").read_text())

    assert manifest["freeze_status"] == "V4 DEVELOPMENT FROZEN"
    assert manifest["retrieval"]["top_k"] == 10
    assert manifest["support_policy"]["support_threshold"] == 2
    assert manifest["historical_representation"]["informative_contexts"] == 350
    assert manifest["historical_representation"]["total_historical_nodes"] == 413


def test_freeze_checksums_include_core_artifacts():
    checksums = json.loads(Path("data/topk_sensitivity_v4/v4_freeze_checksums.json").read_text())

    assert any(path.endswith("data/transmission_context_v1.json") for path in checksums)
    assert "src/v4_config.py" in checksums
    assert "src/mechanism_context.py" in checksums


def test_ambiguous_context_behavior_remains_unresolved():
    from src.transmission_context_store import project_current_event_context

    event = EventAnalysis(
        title="LNG sanctions",
        summary="Sanctions disrupted Arctic LNG shipping.",
        event_type="energy sanctions",
        supply_chain_nodes=["lng_shipping"],
        shock_direction="sanctions",
    )

    assert project_current_event_context(event, "trade_lanes") is None


def test_no_heldout_data_required_for_freeze_artifacts():
    manifest = json.loads(Path("data/topk_sensitivity_v4/v4_final_freeze_manifest.json").read_text())
    source_paths = json.dumps(manifest.get("frozen_files", {})).lower()
    source_paths += json.dumps(manifest.get("artifact_hashes", {})).lower()

    assert "heldout" not in source_paths
    assert "held-out" not in source_paths


def _event() -> EventAnalysis:
    return EventAnalysis(
        title="Red Sea shipping disruption",
        summary="Red Sea shipping routes face disruption.",
        event_type="maritime security disruption",
        supply_chain_nodes=["container_shipping"],
        shock_direction="route disruption",
    )
