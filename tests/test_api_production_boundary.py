from fastapi.testclient import TestClient

from src import api
from src.input_normalizer import NormalizedInput
from src.schemas import EventAnalysis, FinalReport, TransmissionChain
from src.v4_config import (
    METHODOLOGY_VERSION,
    POST_FREEZE_FIX_MANIFEST,
    POST_FREEZE_FIXES_ENABLED,
    PRODUCTION_VERSION,
    V4_CONFIG,
)
from src.v5_config import V5_RECOVERY_APPLICABILITY_CONFIG
from src.v5_models import AnalysisState, V5AnalysisResult
from src.vector_store_health import VectorStoreHealth


def test_analyze_uses_v5_langgraph_with_canonical_config(monkeypatch):
    observed = {}

    def fake_run_v5_langgraph(news_text, event_analyzer=None, config=None):
        observed["news_text"] = news_text
        observed["event_analyzer"] = event_analyzer
        observed["config"] = config
        return _v5_result()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", fake_run_v5_langgraph)

    response = TestClient(api.app).post(
        "/analyze",
        json={"event": "Red Sea Shipping Disruption"},
    )

    assert response.status_code == 200
    assert observed == {
        "news_text": "Red Sea Shipping Disruption",
        "event_analyzer": api.INTERACTIVE_EVENT_ANALYZER,
        "config": V5_RECOVERY_APPLICABILITY_CONFIG,
    }


def test_analyze_returns_final_report_not_v5_wrapper(monkeypatch):
    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", lambda *args, **kwargs: _v5_result())

    response = TestClient(api.app).post(
        "/analyze",
        json={"event": "Red Sea Shipping Disruption"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "event" in payload
    assert "summary" in payload
    assert "state" not in payload
    assert "architecture_version" not in payload


def test_analyze_accepts_event_year_without_exact_date(monkeypatch):
    observed = {}

    def fake_run_v5_langgraph(news_text, event_analyzer=None, config=None):
        observed["news_text"] = news_text
        observed["config"] = config
        return _v5_result()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", fake_run_v5_langgraph)

    response = TestClient(api.app).post(
        "/analyze",
        json={
            "event": "Semiconductor Export Controls",
            "event_year": 2026,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input_title"] == "Semiconductor Export Controls"
    assert payload["input_event_year"] == 2026
    assert payload["input_event_date"] is None
    assert "Year: 2026" in observed["news_text"]
    assert observed["config"] == V5_RECOVERY_APPLICABILITY_CONFIG


def test_analyze_preserves_event_context(monkeypatch):
    observed = {}

    def fake_run_v5_langgraph(news_text, event_analyzer=None, config=None):
        observed["news_text"] = news_text
        return _v5_result()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", fake_run_v5_langgraph)

    response = TestClient(api.app).post(
        "/analyze",
        json={
            "event": "Red Sea Shipping Disruption",
            "context": "Commercial vessels are rerouting around the Cape of Good Hope.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["input_context"] == "Commercial vessels are rerouting around the Cape of Good Hope."
    assert "Context: Commercial vessels" in observed["news_text"]
    assert payload["input_language"] == "English"


def test_non_english_input_is_normalized_at_boundary(monkeypatch):
    observed = {}

    def fake_run_v5_langgraph(news_text, event_analyzer=None, config=None):
        observed["news_text"] = news_text
        observed["config"] = config
        return _v5_result()

    chinese_text = "黑海港口保险限制导致谷物运输延迟。"
    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", fake_run_v5_langgraph)
    monkeypatch.setattr(
        api,
        "normalize_event_input",
        lambda text: NormalizedInput(
            original_text=text,
            analysis_text="Black Sea port insurance restrictions delay grain shipping.",
            detected_language="Chinese",
            normalization_applied=True,
        ),
    )

    response = TestClient(api.app).post("/analyze", json={"event": chinese_text})

    assert response.status_code == 200
    assert observed["news_text"] == "Black Sea port insurance restrictions delay grain shipping."
    assert observed["config"] == V5_RECOVERY_APPLICABILITY_CONFIG
    assert response.json()["original_event_text"] == chinese_text
    assert response.json()["input_language"] == "Chinese"
    assert response.json()["input_normalization_applied"] is True


def test_non_english_input_fails_cleanly_when_normalization_unavailable(monkeypatch):
    called = {"v5": False}

    def fake_run_v5_langgraph(news_text, event_analyzer=None, config=None):
        called["v5"] = True
        return _v5_result()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", fake_run_v5_langgraph)
    monkeypatch.setattr(
        api,
        "normalize_event_input",
        lambda text: NormalizedInput(
            original_text=text,
            analysis_text=text,
            detected_language="Chinese",
            normalization_applied=False,
            normalization_error="InputNormalizationError: OPENAI_API_KEY is not configured.",
        ),
    )

    response = TestClient(api.app).post("/analyze", json={"event": "黑海港口保险限制导致谷物运输延迟。"})

    assert response.status_code == 503
    assert "submit the event in English" in response.json()["detail"]
    assert called["v5"] is False


def test_analyze_rejects_production_top_k_override(monkeypatch):
    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", lambda *args, **kwargs: _v5_result())

    response = TestClient(api.app).post(
        "/analyze",
        json={
            "event": "Red Sea shipping routes face disruption.",
            "top_k": 3,
        },
    )

    assert response.status_code == 422


def test_analyze_accepts_legacy_news_text_alias(monkeypatch):
    observed = {}

    def fake_run_v5_langgraph(news_text, event_analyzer=None, config=None):
        observed["news_text"] = news_text
        return _v5_result()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v5_langgraph", fake_run_v5_langgraph)

    response = TestClient(api.app).post(
        "/analyze",
        json={"news_text": "Red Sea shipping routes face disruption."},
    )

    assert response.status_code == 200
    assert observed["news_text"] == "Red Sea shipping routes face disruption."


def test_analyze_rejects_empty_description():
    response = TestClient(api.app).post("/analyze", json={"event": "   "})

    assert response.status_code == 422


def test_health_reports_ready_vector_store(monkeypatch):
    monkeypatch.setattr(
        api,
        "validate_vector_store",
        lambda: VectorStoreHealth(
            chroma_version="1.5.9",
            persistence_path="chroma_db",
            collection_name="georisk_historical_cases",
            collection_count=70,
            healthy=True,
            message="OK",
        ),
    )

    response = TestClient(api.app).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["vector_store"]["status"] == "ready"
    assert payload["vector_store"]["documents"] == 70


def test_health_reports_unhealthy_vector_store(monkeypatch):
    monkeypatch.setattr(
        api,
        "validate_vector_store",
        lambda: VectorStoreHealth(
            chroma_version="1.5.9",
            persistence_path="chroma_db",
            collection_name="georisk_historical_cases",
            collection_count=None,
            healthy=False,
            message="Expected collection is missing.",
        ),
    )

    response = TestClient(api.app).get("/health")

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "unhealthy"


def test_version_reflects_v5_langgraph_runtime_and_frozen_v4_boundary():
    response = TestClient(api.app).get("/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["production_version"] == PRODUCTION_VERSION
    assert payload["methodology_version"] == METHODOLOGY_VERSION
    assert payload["version"] == PRODUCTION_VERSION
    assert "V5 LangGraph" in payload["runtime"]
    assert "Frozen V4" in payload["runtime"]
    assert payload["post_freeze_fixes"] == POST_FREEZE_FIXES_ENABLED
    assert payload["post_freeze_fix_manifest"] == POST_FREEZE_FIX_MANIFEST
    configuration = payload["configuration"]
    assert configuration["top_k"] == V4_CONFIG.retrieval_top_k
    assert configuration["support_threshold"] == V4_CONFIG.compatible_support_threshold
    assert configuration["mechanism_compatible"] == V4_CONFIG.use_mechanism_compatible_support
    assert configuration["architecture_version"] == V5_RECOVERY_APPLICABILITY_CONFIG.architecture_version
    assert "Frozen V4" in configuration["verification_boundary"]
    assert configuration["max_repair_attempts"] == 1
    assert configuration["max_new_candidate_nodes"] == 5
    assert configuration["node_repair_enabled"] is True
    assert configuration["specificity_recovery_enabled"] is True
    assert configuration["current_event_applicability_gate_enabled"] is True


def _report() -> FinalReport:
    event = EventAnalysis(
        title="Red Sea disruption",
        summary="Shipping disruption.",
        event_type="maritime_security_disruption",
        regions=["Middle East"],
        supply_chain_nodes=["maritime_chokepoint"],
        shock_direction="disruption",
    )
    chain = TransmissionChain(
        chain_steps=["Shipping routes disrupted"],
        affected_nodes=["maritime_chokepoint"],
        rationale="Retrieved cases support maritime disruption risk.",
    )
    return FinalReport(
        event=event,
        retrieved_cases=[],
        transmission_chain=chain,
        evidence_results=[],
        summary="GeoRisk report.",
        event_summary="Shipping disruption.",
        retrieved_case_summaries=[],
        secondary_asset_watchlist={},
        disclaimer="Risk watchlist only. Not investment advice.",
    )


def _v5_result() -> V5AnalysisResult:
    report = _report()
    return V5AnalysisResult(
        final_report=report,
        architecture_version=V5_RECOVERY_APPLICABILITY_CONFIG.architecture_version,
        repair_policy_version=V5_RECOVERY_APPLICABILITY_CONFIG.repair_policy_version,
        repair_enabled=V5_RECOVERY_APPLICABILITY_CONFIG.enable_node_repair,
        state=AnalysisState(
            event=report.event,
            direct_nodes=list(report.event.supply_chain_nodes),
            candidate_nodes=list(report.event.supply_chain_nodes),
            status="FINAL",
        ),
    )
