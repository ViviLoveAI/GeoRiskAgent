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
from src.vector_store_health import VectorStoreHealth


def test_analyze_uses_v4_production_pipeline(monkeypatch):
    observed = {}

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        observed["news_text"] = news_text
        observed["event_analyzer"] = event_analyzer
        return _report()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v4_pipeline", fake_run_v4_pipeline)

    response = TestClient(api.app).post(
        "/analyze",
        json={"event": "Red Sea Shipping Disruption"},
    )

    assert response.status_code == 200
    assert observed == {
        "news_text": "Red Sea Shipping Disruption",
        "event_analyzer": api.INTERACTIVE_EVENT_ANALYZER,
    }


def test_analyze_accepts_event_year_without_exact_date(monkeypatch):
    observed = {}

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        observed["news_text"] = news_text
        return _report()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v4_pipeline", fake_run_v4_pipeline)

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


def test_analyze_preserves_event_context(monkeypatch):
    observed = {}

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        observed["news_text"] = news_text
        return _report()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v4_pipeline", fake_run_v4_pipeline)

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

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        observed["news_text"] = news_text
        return _report()

    chinese_text = "黑海港口保险限制导致谷物运输延迟。"
    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v4_pipeline", fake_run_v4_pipeline)
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
    assert response.json()["original_event_text"] == chinese_text
    assert response.json()["input_language"] == "Chinese"
    assert response.json()["input_normalization_applied"] is True


def test_non_english_input_fails_cleanly_when_normalization_unavailable(monkeypatch):
    called = {"pipeline": False}

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        called["pipeline"] = True
        return _report()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v4_pipeline", fake_run_v4_pipeline)
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
    assert called["pipeline"] is False


def test_analyze_rejects_production_top_k_override(monkeypatch):
    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v4_pipeline", lambda *args, **kwargs: _report())

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

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        observed["news_text"] = news_text
        return _report()

    monkeypatch.setattr(api, "assert_vector_store_ready", lambda: None)
    monkeypatch.setattr(api, "run_v4_pipeline", fake_run_v4_pipeline)

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


def test_version_reflects_canonical_v4_config():
    response = TestClient(api.app).get("/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["production_version"] == PRODUCTION_VERSION
    assert payload["methodology_version"] == METHODOLOGY_VERSION
    assert payload["version"] == PRODUCTION_VERSION
    assert payload["post_freeze_fixes"] == POST_FREEZE_FIXES_ENABLED
    assert payload["post_freeze_fix_manifest"] == POST_FREEZE_FIX_MANIFEST
    configuration = payload["configuration"]
    assert configuration["top_k"] == V4_CONFIG.retrieval_top_k
    assert configuration["support_threshold"] == V4_CONFIG.compatible_support_threshold
    assert configuration["mechanism_compatible"] == V4_CONFIG.use_mechanism_compatible_support


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
