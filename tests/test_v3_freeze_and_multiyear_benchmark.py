import csv
import json
from pathlib import Path

import pytest

from scripts.build_v3_frozen_baseline import build_v3_frozen_baseline
from src.validation.multiyear_general_benchmark import (
    BENCHMARK_VERSION,
    CHECKSUMS_PATH,
    FINAL_EVENTS_PATH,
    GROUND_TRUTH_PATH,
    MANIFEST_PATH,
    assert_multiyear_ready_for_prediction,
    seal_multiyear_general_benchmark,
)
from src.v3_config import V3_CONFIG, assert_v3_config


def test_v3_config_freezes_pre_v4_semantics():
    assert V3_CONFIG.baseline_version == "georisk_v3_frozen_v1"
    assert V3_CONFIG.event_analyzer == "rule"
    assert V3_CONFIG.retrieval_top_k == 3
    assert V3_CONFIG.support_threshold == 2
    assert V3_CONFIG.transmission_context_enabled is False
    assert V3_CONFIG.mechanism_compatibility_enabled is False
    assert V3_CONFIG.canonical_family_enabled is False
    assert_v3_config(V3_CONFIG)


def test_run_v3_pipeline_uses_top_k_3_and_no_mechanism_context(monkeypatch):
    observed = {}

    def fake_analyze(text):
        from src.schemas import EventAnalysis

        return EventAnalysis(
            title="Fixture",
            summary=text,
            event_type="fixture",
            regions=["Global"],
            industries=["shipping"],
            supply_chain_nodes=["ports"],
            shock_direction="restriction",
            risk_factors=[],
        )

    def fake_retrieve(news_text, event, top_k=5):
        observed["top_k"] = top_k
        return []

    def fake_build(event, retrieved_cases, *, use_mechanism_compatible_support=None):
        from src.schemas import TransmissionChain

        observed["mechanism_flag"] = use_mechanism_compatible_support
        return TransmissionChain(
            chain_steps=[],
            affected_nodes=["ports"],
            node_supporting_case_ids={"ports": []},
            node_evidence_levels={"ports": "event_node"},
            supporting_case_ids=[],
            rationale="fixture",
        )

    monkeypatch.setattr("src.pipeline.analyze_event", fake_analyze)
    monkeypatch.setattr("src.pipeline.retrieve_cases", fake_retrieve)
    monkeypatch.setattr("src.pipeline.build_transmission_chain", fake_build)
    monkeypatch.setattr("src.pipeline.map_assets", lambda *args: [])
    monkeypatch.setattr("src.pipeline.grade_evidence", lambda *args: [])
    monkeypatch.setattr("src.pipeline.rank_assets", lambda *args: [])

    from src.pipeline import run_v3_pipeline

    run_v3_pipeline("fixture event")

    assert observed["top_k"] == 3
    assert observed["mechanism_flag"] is False


def test_v3_freeze_artifacts_created():
    result = build_v3_frozen_baseline()
    manifest = json.loads(Path(result["manifest"]).read_text())
    trace = json.loads(Path(result["trace"]).read_text())

    assert manifest["baseline_version"] == "georisk_v3_frozen_v1"
    assert manifest["resolved_config"]["retrieval_top_k"] == 3
    assert manifest["resolved_config"]["TransmissionContext_enabled"] is False
    assert trace["resolved_v3_top_k"] == 3


def test_multiyear_benchmark_seals_without_predictions():
    build_v3_frozen_baseline()
    result = seal_multiyear_general_benchmark()
    manifest = json.loads(Path(MANIFEST_PATH).read_text())

    assert result["ready_for_paired_prediction"] is True
    assert manifest["benchmark_version"] == BENCHMARK_VERSION
    assert manifest["prediction_status"]["V3_predictions_run"] is False
    assert manifest["prediction_status"]["V4_predictions_run"] is False
    assert manifest["prediction_status"]["prices_accessed"] is False
    assert manifest["prediction_status"]["CAR_run"] is False


def test_multiyear_years_restricted_to_2020_2025():
    build_v3_frozen_baseline()
    seal_multiyear_general_benchmark()
    rows = _rows(FINAL_EVENTS_PATH)

    assert rows
    assert {row["event_year"] for row in rows}.issubset({"2020", "2021", "2022", "2023", "2024", "2025"})
    assert "2026" not in {row["event_year"] for row in rows}


def test_multiyear_screening_rejects_overlap_and_temporal_events_absent():
    build_v3_frozen_baseline()
    seal_multiyear_general_benchmark()
    screening = _rows("data/validation_general/multiyear_candidate_screening.csv")
    final_ids = {row["candidate_id"] for row in _rows(FINAL_EVENTS_PATH)}

    assert any(row["eligibility_status"] == "reject_exact_kb_overlap" for row in screening)
    assert any(row["eligibility_status"] == "reject_prior_validation_overlap" for row in screening)
    assert not any(row["candidate_id"].startswith("v4cand_2026") for row in screening)
    assert all(
        row["eligibility_status"] == "eligible"
        for row in screening
        if row["candidate_id"] in final_ids
    )


def test_multiyear_ground_truth_has_no_model_or_market_fields():
    build_v3_frozen_baseline()
    seal_multiyear_general_benchmark()
    rows = _rows(GROUND_TRUTH_PATH)
    fields = set(rows[0])

    forbidden = {
        "V3_prediction",
        "V4_prediction",
        "CAR",
        "SCAR",
        "return",
        "realized_return",
        "price_before",
        "price_after",
    }
    assert rows
    assert fields.isdisjoint(forbidden)
    assert {row["expected_support_class"] for row in rows}.issubset(
        {
            "compatible_support_expected",
            "weak_cooccurrence_expected",
            "insufficient_context_expected",
        }
    )


def test_multiyear_checksums_detect_event_mutation(tmp_path):
    build_v3_frozen_baseline()
    seal_multiyear_general_benchmark()
    final_events = Path(FINAL_EVENTS_PATH)
    original = final_events.read_text(encoding="utf-8")
    final_events.write_text(original + "\n", encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="checksum_mismatch"):
            assert_multiyear_ready_for_prediction()
    finally:
        final_events.write_text(original, encoding="utf-8")


def test_multiyear_readiness_requires_v3_and_v4_freezes():
    build_v3_frozen_baseline()
    seal_multiyear_general_benchmark()

    with pytest.raises(FileNotFoundError):
        assert_multiyear_ready_for_prediction(
            manifest_path=MANIFEST_PATH,
            checksums_path=CHECKSUMS_PATH,
            v3_manifest_path="missing_v3_manifest.json",
        )


def _rows(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
