import requests
import json
from contextlib import contextmanager
from inspect import signature
from pathlib import Path

import app
from src.schemas import EventAnalysis, FinalReport, TransmissionChain


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else _report().model_dump(mode="json")

    def json(self):
        return self._payload


def test_streamlit_request_analysis_parses_report(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse()

    monkeypatch.setattr(app.requests, "post", fake_post)

    report = app._request_analysis("Red Sea shipping routes face disruption.")

    assert report.event.title == "Red Sea disruption"
    assert calls[0][0].endswith("/analyze")
    assert calls[0][1] == {"event": "Red Sea shipping routes face disruption."}


def test_streamlit_request_analysis_sends_optional_year_and_context(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return FakeResponse()

    monkeypatch.setattr(app.requests, "post", fake_post)

    app._request_analysis(
        "Red Sea Shipping Disruption",
        event_year=2026,
        context="Commercial vessels are rerouting around the Cape of Good Hope.",
    )

    assert calls[0] == {
        "event": "Red Sea Shipping Disruption",
        "event_year": 2026,
        "context": "Commercial vessels are rerouting around the Cape of Good Hope.",
    }


def test_streamlit_request_analysis_sends_non_ascii_event_year_without_empty_context(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return FakeResponse()

    monkeypatch.setattr(app.requests, "post", fake_post)

    app._request_analysis("中美关税摩擦", event_year=2026, context=None)

    assert calls[0] == {
        "event": "中美关税摩擦",
        "event_year": 2026,
    }


def test_homepage_showcase_examples_are_curated_to_two_events():
    labels = [event["label"] for event in app.EXAMPLE_EVENTS]

    assert labels == [
        "Semiconductor Export Controls",
        "Energy & Fertilizer Shock",
    ]
    assert "Red Sea Shipping Disruption" not in labels
    assert "US-China Tariff Escalation" not in labels


def test_red_sea_and_tariff_regression_cases_remain_available():
    cases = json.loads(Path("data/historical_cases.json").read_text(encoding="utf-8"))
    haystack = " ".join(
        [
            str(case.get("event_name", "")) + " " + str(case.get("retrieval_text", ""))
            for case in cases
        ]
    ).lower()

    assert "red sea" in haystack
    assert "tariff" in haystack


def test_custom_event_submit_sends_no_default_year(monkeypatch):
    submitted = []
    warnings = []

    def fake_analyze(event, event_label, *, event_year=None, context=None):
        submitted.append(
            {
                "event": event,
                "event_label": event_label,
                "event_year": event_year,
                "context": context,
            }
        )

    monkeypatch.setattr(app, "_analyze_and_open_report", fake_analyze)
    monkeypatch.setattr(app.st, "warning", lambda message: warnings.append(message))

    app._handle_custom_event_submit("US-China Tariff Escalation", "")

    assert warnings == []
    assert submitted == [
        {
            "event": "US-China Tariff Escalation",
            "event_label": "US-China Tariff Escalation",
            "event_year": None,
            "context": None,
        }
    ]


def test_custom_event_submit_only_requires_event_and_optional_context():
    parameters = list(signature(app._handle_custom_event_submit).parameters)

    assert parameters == ["custom_event", "custom_context"]


def test_custom_event_submit_empty_input_is_validation_not_service_error(monkeypatch):
    warnings = []

    monkeypatch.setattr(app.st, "warning", lambda message: warnings.append(message))
    app.st.session_state.service_error = ""

    app._handle_custom_event_submit("   ", "")

    assert warnings == ["Enter an event to continue."]
    assert app.st.session_state.service_error == ""


def test_watchlist_partition_keeps_first_order_out_of_ranked_results():
    report = _report()
    report.secondary_asset_watchlist = {
        "historical_supported": [
            {
                "ticker": "BOAT",
                "asset_name": "Shipping ETF",
                "ranking_scope": "reference_first_order",
                "rank_within_order": 1,
            },
            {
                "ticker": "DHL.DE",
                "asset_name": "DHL Group",
                "ranking_scope": "ranked_second_order",
                "rank_within_order": 1,
            },
        ],
        "sector_proxy": [
            {
                "ticker": "EXPD",
                "asset_name": "Expeditors",
                "ranking_scope": "ranked_second_order",
                "rank_within_order": 2,
            }
        ],
    }

    ranked, direct, unclassified = app._partition_watchlist_assets(report)

    assert [asset["ticker"] for asset in ranked] == ["DHL.DE", "EXPD"]
    assert [asset["ticker"] for asset in direct] == ["BOAT"]
    assert unclassified == []


def test_secondary_channel_summary_connects_channels_to_ranked_tickers():
    summary = app._secondary_channel_summary(
        ["logistics"],
        {"logistics": [{"ticker": "DHL.DE"}, {"ticker": "EXPD"}]},
    )

    assert "Logistics Networks -> DHL.DE · EXPD" in summary


def test_empty_second_order_state_copy_is_analytical_abstention():
    assert "No qualified second-order exposures" in app.SECOND_ORDER_EMPTY_STATE_TITLE
    assert "historical-support" in app.SECOND_ORDER_EMPTY_STATE_BODY
    assert "Transmission Path" in app.SECOND_ORDER_EMPTY_STATE_BODY


def test_report_navigation_order_prioritizes_results_before_evidence():
    assert app.REPORT_SECTIONS == [
        ("summary", "Overview"),
        ("watchlist", "Watchlist"),
        ("transmission", "Transmission"),
        ("evidence", "Evidence"),
    ]


def test_compact_node_list_limits_overview_noise():
    value = app._compact_node_list(
        ["ai_chips", "semiconductor_equipment", "data_centers"],
        limit=2,
    )

    assert "AI Chips" in value
    assert "Semiconductor Equipment" in value
    assert "+1 more" in value


def test_watchlist_disclaimer_content_remains_available():
    assert "not price forecasts" in app.REPORT_FOOTER_DISCLAIMER
    assert "investment advice" in app.REPORT_FOOTER_DISCLAIMER


def test_direct_reference_asset_summary_groups_assets_without_ranks():
    summary = app._direct_reference_asset_summary(
        [
            {
                "ticker": "DAC",
                "supply_chain_node": "container_shipping",
                "ranking_scope": "reference_first_order",
            },
            {
                "ticker": "MAERSK-B.CO",
                "supply_chain_node": "container_shipping",
                "ranking_scope": "reference_first_order",
            },
            {
                "ticker": "DHT",
                "supply_chain_node": "oil_shipping",
                "ranking_scope": "reference_first_order",
            },
        ]
    )

    assert "Container Shipping" in summary
    assert "DAC" in summary
    assert "MAERSK-B.CO" in summary
    assert "Oil Tanker Shipping" in summary
    assert "#1" not in summary
    assert "Priority" not in summary


def test_direct_reference_groups_are_compact_and_grouped_by_node():
    groups = app._direct_reference_groups(
        [
            {
                "ticker": "MPC",
                "asset_name": "Marathon Petroleum",
                "supply_chain_node": "refining",
                "evidence_level": "inference_only",
                "rank_within_order": 99,
            },
            {
                "ticker": "VLO",
                "asset_name": "Valero",
                "supply_chain_node": "refining",
                "evidence_level": "sector_proxy",
            },
            {
                "ticker": "CAT",
                "asset_name": "Caterpillar",
                "supply_chain_node": "manufacturing_inputs",
                "evidence_level": "sector_proxy",
            },
        ]
    )

    by_node = {group["node"]: group for group in groups}
    assert by_node["refining"]["ticker_text"] == "VLO · MPC"
    assert by_node["manufacturing_inputs"]["ticker_text"] == "CAT"
    assert "rank" not in str(by_node["refining"]["ticker_text"]).lower()


def test_direct_reference_table_rows_have_no_rank_column():
    rows = app._asset_table_rows(
        [
            {
                "ticker": "DHT",
                "asset_name": "DHT Holdings Inc",
                "supply_chain_node": "oil_shipping",
                "evidence_level": "sector_proxy",
                "rank_within_order": 1,
            }
        ],
        show_rank=False,
        include_transmission=False,
    )

    assert "Rank" not in rows[0]
    assert rows[0]["Ticker"] == "DHT"


def test_ranked_second_order_table_rows_keep_rank_column():
    rows = app._asset_table_rows(
        [
            {
                "ticker": "DHL.DE",
                "asset_name": "DHL Group",
                "supply_chain_node": "trade_lanes",
                "evidence_level": "sector_proxy",
                "rank_within_order": 2,
            }
        ],
        show_rank=True,
        include_transmission=False,
    )

    assert rows[0]["Rank"] == "2"


def test_inference_only_badge_uses_neutral_indicator():
    assert app._evidence_badge("inference_only") == "⚪ Inference Only"


def test_zero_second_order_state_copy_points_to_direct_references():
    assert "No qualified second-order exposures" in app.SECOND_ORDER_EMPTY_STATE_TITLE
    assert "Direct exposures" in app.SECOND_ORDER_EMPTY_STATE_BODY


def test_analyze_service_failure_sets_global_message(monkeypatch):
    errors = []

    @contextmanager
    def fake_spinner(message):
        yield

    def fake_request(*args, **kwargs):
        raise app.GeoRiskAPIClientError("GeoRisk analysis service is temporarily unavailable.")

    monkeypatch.setattr(app.st, "spinner", fake_spinner)
    monkeypatch.setattr(app, "_request_analysis", fake_request)
    monkeypatch.setattr(app.st, "rerun", lambda: errors.append("rerun"))
    app.st.session_state.service_error = ""

    app._analyze_and_open_report("Red Sea Shipping Disruption", "Red Sea")

    assert app.st.session_state.service_error == "GeoRisk analysis service is temporarily unavailable."
    assert errors == ["rerun"]


def test_streamlit_request_analysis_handles_timeout(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.Timeout("slow")

    monkeypatch.setattr(app.requests, "post", fake_post)

    try:
        app._request_analysis("Red Sea shipping routes face disruption.")
    except app.GeoRiskAPIClientError as exc:
        assert "taking longer" in exc.user_message
    else:
        raise AssertionError("expected GeoRiskAPIClientError")


def test_streamlit_request_analysis_handles_backend_unavailable(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.ConnectionError("unreachable")

    monkeypatch.setattr(app.requests, "post", fake_post)

    try:
        app._request_analysis("Red Sea shipping routes face disruption.")
    except app.GeoRiskAPIClientError as exc:
        assert "service is temporarily unavailable" in exc.user_message
    else:
        raise AssertionError("expected GeoRiskAPIClientError")


def test_streamlit_request_analysis_maps_retrieval_failure(monkeypatch):
    def fake_post(url, json, timeout):
        return FakeResponse(
            status_code=503,
            payload={
                "detail": {
                    "status": "unhealthy",
                    "vector_store": {"status": "unavailable"},
                }
            },
        )

    monkeypatch.setattr(app.requests, "post", fake_post)

    try:
        app._request_analysis("Red Sea shipping routes face disruption.")
    except app.GeoRiskAPIClientError as exc:
        assert "Historical-case retrieval" in exc.user_message
    else:
        raise AssertionError("expected GeoRiskAPIClientError")


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
