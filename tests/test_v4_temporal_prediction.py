import csv
import json
from pathlib import Path

import pytest

from src.schemas import (
    CandidateAsset,
    EventAnalysis,
    EvidenceResult,
    FinalReport,
    RetrievedCase,
    TransmissionChain,
)
from src.validation.v4_temporal_prediction import (
    ATTEMPT_001_ID,
    ATTEMPT_002_ID,
    assert_prediction_checksums_valid,
    evaluate_frozen_temporal_mechanisms,
    run_and_freeze_temporal_predictions,
)


def test_prediction_refuses_when_temporal_checksum_invalid(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    event_file = paths["final_events_path"]
    event_file.write_text(event_file.read_text() + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checksum_mismatch"):
        run_and_freeze_temporal_predictions(
            final_events_path=event_file,
            temporal_manifest_path=paths["temporal_manifest_path"],
            temporal_checksums_path=paths["temporal_checksums_path"],
            freeze_manifest_path=paths["freeze_manifest_path"],
            freeze_checksums_path=paths["freeze_checksums_path"],
            prediction_dir=tmp_path / "predictions",
        )


def test_prediction_refuses_when_v4_freeze_checksum_invalid(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    v4_config = Path("src/v4_config.py")
    paths["freeze_checksums_path"].write_text(
        json.dumps({"artifacts": {str(v4_config): "bad"}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="v4_freeze_checksum_mismatch"):
        run_and_freeze_temporal_predictions(
            final_events_path=paths["final_events_path"],
            temporal_manifest_path=paths["temporal_manifest_path"],
            temporal_checksums_path=paths["temporal_checksums_path"],
            freeze_manifest_path=paths["freeze_manifest_path"],
            freeze_checksums_path=paths["freeze_checksums_path"],
            prediction_dir=tmp_path / "predictions",
        )


def test_prediction_uses_only_run_v4_pipeline_and_freezes_snapshots(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    calls = []

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        calls.append((news_text, event_analyzer))
        return _report()

    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", fake_run_v4_pipeline)

    result = run_and_freeze_temporal_predictions(
        final_events_path=paths["final_events_path"],
        temporal_manifest_path=paths["temporal_manifest_path"],
        temporal_checksums_path=paths["temporal_checksums_path"],
        freeze_manifest_path=paths["freeze_manifest_path"],
        freeze_checksums_path=paths["freeze_checksums_path"],
        prediction_dir=tmp_path / "predictions",
    )

    assert len(calls) == 16
    assert all(call[1] == "rule" for call in calls)
    assert result["events_attempted"] == 16
    assert result["successful"] == 16
    assert result["runtime_failures"] == 0
    assert Path(result["raw_prediction_artifact"]).exists()
    assert Path(result["node_snapshot"]).exists()
    assert Path(result["asset_snapshot"]).exists()
    assert_prediction_checksums_valid(result["prediction_checksums"])


def test_frozen_config_is_recorded_in_manifest(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", lambda *args, **kwargs: _report())

    result = run_and_freeze_temporal_predictions(
        final_events_path=paths["final_events_path"],
        temporal_manifest_path=paths["temporal_manifest_path"],
        temporal_checksums_path=paths["temporal_checksums_path"],
        freeze_manifest_path=paths["freeze_manifest_path"],
        freeze_checksums_path=paths["freeze_checksums_path"],
        prediction_dir=tmp_path / "predictions",
    )
    manifest = json.loads(Path(result["prediction_manifest"]).read_text())

    assert manifest["v4_config"]["top_k"] == 10
    assert manifest["v4_config"]["mechanism_compatible_support"] is True
    assert manifest["v4_config"]["support_threshold"] == 2
    assert manifest["v4_config"]["transmission_context_version"] == "transmission_context_v1"
    assert manifest["v4_config"]["canonical_family_version"] == "canonical_family_v1"
    assert manifest["v4_config"]["mechanism_compatibility_version"] == "mechanism_compatibility_candidate_v1"
    assert manifest["ground_truth_accessed_during_generation"] is False
    assert manifest["prices_accessed"] is False
    assert manifest["CAR_run"] is False


def test_prediction_cannot_be_silently_overwritten_after_freeze(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", lambda *args, **kwargs: _report())

    kwargs = {
        "final_events_path": paths["final_events_path"],
        "temporal_manifest_path": paths["temporal_manifest_path"],
        "temporal_checksums_path": paths["temporal_checksums_path"],
        "freeze_manifest_path": paths["freeze_manifest_path"],
        "freeze_checksums_path": paths["freeze_checksums_path"],
        "prediction_dir": tmp_path / "predictions",
    }
    run_and_freeze_temporal_predictions(**kwargs)
    status = paths["status_path"]
    status.write_text(json.dumps({"predictions_frozen": False, "car_run": False}), encoding="utf-8")

    with pytest.raises(FileExistsError):
        run_and_freeze_temporal_predictions(**kwargs)


def test_prediction_checksum_detects_mutation(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", lambda *args, **kwargs: _report())
    result = run_and_freeze_temporal_predictions(
        final_events_path=paths["final_events_path"],
        temporal_manifest_path=paths["temporal_manifest_path"],
        temporal_checksums_path=paths["temporal_checksums_path"],
        freeze_manifest_path=paths["freeze_manifest_path"],
        freeze_checksums_path=paths["freeze_checksums_path"],
        prediction_dir=tmp_path / "predictions",
    )
    node_snapshot = Path(result["node_snapshot"])
    node_snapshot.write_text(node_snapshot.read_text() + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="prediction_checksum_mismatch"):
        assert_prediction_checksums_valid(result["prediction_checksums"])


def test_evaluation_requires_prediction_freeze(tmp_path):
    with pytest.raises(FileNotFoundError):
        evaluate_frozen_temporal_mechanisms(
            ground_truth_path=tmp_path / "ground_truth.csv",
            node_snapshot_path=tmp_path / "node_snapshot.csv",
            prediction_checksums_path=tmp_path / "missing_checksums.json",
            output_path=tmp_path / "eval.csv",
            summary_path=tmp_path / "summary.json",
            error_path=tmp_path / "errors.csv",
        )


def test_evaluation_after_freeze_produces_metrics(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", lambda *args, **kwargs: _report())
    result = run_and_freeze_temporal_predictions(
        final_events_path=paths["final_events_path"],
        temporal_manifest_path=paths["temporal_manifest_path"],
        temporal_checksums_path=paths["temporal_checksums_path"],
        freeze_manifest_path=paths["freeze_manifest_path"],
        freeze_checksums_path=paths["freeze_checksums_path"],
        prediction_dir=tmp_path / "predictions",
    )

    summary = evaluate_frozen_temporal_mechanisms(
        ground_truth_path=paths["ground_truth_path"],
        node_snapshot_path=result["node_snapshot"],
        prediction_checksums_path=result["prediction_checksums"],
        output_path=tmp_path / "eval.csv",
        summary_path=tmp_path / "summary.json",
        error_path=tmp_path / "errors.csv",
    )

    assert summary["total_annotations"] == 32
    assert "compatible_retention_rate" in summary
    assert summary["prices_accessed"] is False
    assert summary["CAR_run"] is False


def test_attempt_002_controlled_retry_allowed_after_failed_attempt_001(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    paths["status_path"].write_text(
        json.dumps(
            {
                "ground_truth_frozen": True,
                "heldout_manifest_sealed": True,
                "predictions_frozen": True,
                "car_run": False,
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run_v4_pipeline(news_text, event_analyzer=None):
        calls.append((news_text, event_analyzer))
        return _report()

    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", fake_run_v4_pipeline)

    result = run_and_freeze_temporal_predictions(
        final_events_path=paths["final_events_path"],
        temporal_manifest_path=paths["temporal_manifest_path"],
        temporal_checksums_path=paths["temporal_checksums_path"],
        freeze_manifest_path=paths["freeze_manifest_path"],
        freeze_checksums_path=paths["freeze_checksums_path"],
        prediction_dir=tmp_path / "attempt_002",
        attempt_id=ATTEMPT_002_ID,
        parent_attempt=ATTEMPT_001_ID,
        retry_reason="execution_client_lifecycle_fix",
        attempt_type="controlled_execution_retry",
        allow_controlled_retry_after_frozen=True,
    )
    manifest = json.loads(Path(result["prediction_manifest"]).read_text(encoding="utf-8"))
    status = json.loads(paths["status_path"].read_text(encoding="utf-8"))

    assert len(calls) == 16
    assert all(call[1] == "rule" for call in calls)
    assert Path(result["raw_prediction_artifact"]).parent.name == "attempt_002"
    assert result["attempt_id"] == ATTEMPT_002_ID
    assert result["parent_attempt"] == ATTEMPT_001_ID
    assert result["retry_reason"] == "execution_client_lifecycle_fix"
    assert result["valid_prediction_snapshot_available"] is True
    assert manifest["attempt_id"] == ATTEMPT_002_ID
    assert manifest["parent_attempt"] == ATTEMPT_001_ID
    assert manifest["retry_reason"] == "execution_client_lifecycle_fix"
    assert manifest["attempt_type"] == "controlled_execution_retry"
    assert manifest["ground_truth_accessed_during_generation"] is False
    assert manifest["prices_accessed"] is False
    assert manifest["returns_accessed"] is False
    assert manifest["CAR_run"] is False
    assert manifest["semantic_config_changed"] is False
    assert manifest["benchmark_changed"] is False
    assert manifest["ground_truth_changed"] is False
    assert status["latest_prediction_attempt"] == ATTEMPT_002_ID
    assert status[f"{ATTEMPT_002_ID}_frozen"] is True
    assert status[f"{ATTEMPT_002_ID}_status"] == "completed"
    assert status["valid_prediction_snapshot_available"] is True


def test_attempt_002_requires_exact_retry_metadata(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    paths["status_path"].write_text(
        json.dumps({"predictions_frozen": True, "car_run": False}),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", lambda *args, **kwargs: _report())

    with pytest.raises(RuntimeError, match="controlled_retry_preflight_failed:wrong_retry_reason"):
        run_and_freeze_temporal_predictions(
            final_events_path=paths["final_events_path"],
            temporal_manifest_path=paths["temporal_manifest_path"],
            temporal_checksums_path=paths["temporal_checksums_path"],
            freeze_manifest_path=paths["freeze_manifest_path"],
            freeze_checksums_path=paths["freeze_checksums_path"],
            prediction_dir=tmp_path / "attempt_002",
            attempt_id=ATTEMPT_002_ID,
            parent_attempt=ATTEMPT_001_ID,
            retry_reason="different_reason",
            allow_controlled_retry_after_frozen=True,
        )


def test_attempt_002_evaluation_starts_only_after_snapshot_freeze(tmp_path, monkeypatch):
    paths = _fixture_paths(tmp_path, monkeypatch)
    paths["status_path"].write_text(
        json.dumps(
            {
                "ground_truth_frozen": True,
                "heldout_manifest_sealed": True,
                "predictions_frozen": True,
                "car_run": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.validation.v4_temporal_prediction.run_v4_pipeline", lambda *args, **kwargs: _report())
    attempt_dir = tmp_path / "attempt_002"
    result = run_and_freeze_temporal_predictions(
        final_events_path=paths["final_events_path"],
        temporal_manifest_path=paths["temporal_manifest_path"],
        temporal_checksums_path=paths["temporal_checksums_path"],
        freeze_manifest_path=paths["freeze_manifest_path"],
        freeze_checksums_path=paths["freeze_checksums_path"],
        prediction_dir=attempt_dir,
        attempt_id=ATTEMPT_002_ID,
        parent_attempt=ATTEMPT_001_ID,
        retry_reason="execution_client_lifecycle_fix",
        attempt_type="controlled_execution_retry",
        allow_controlled_retry_after_frozen=True,
    )

    summary = evaluate_frozen_temporal_mechanisms(
        ground_truth_path=paths["ground_truth_path"],
        node_snapshot_path=result["node_snapshot"],
        prediction_checksums_path=result["prediction_checksums"],
        output_path=tmp_path / "results" / "eval.csv",
        summary_path=tmp_path / "results" / "summary.json",
        error_path=tmp_path / "results" / "errors.csv",
    )

    assert summary["total_annotations"] == 32
    assert Path(result["prediction_checksums"]).exists()
    assert Path(tmp_path / "results" / "eval.csv").exists()
    assert summary["prices_accessed"] is False
    assert summary["CAR_run"] is False


def _fixture_paths(tmp_path, monkeypatch):
    from src.validation.v4_temporal_heldout import (
        CHECKSUMS_PATH,
        FINAL_EVENTS_PATH,
        GROUND_TRUTH_PATH,
        MANIFEST_PATH,
    )

    final_events = tmp_path / "temporal_final_heldout_events.csv"
    final_events.write_text(Path(FINAL_EVENTS_PATH).read_text(), encoding="utf-8")
    ground_truth = tmp_path / "temporal_heldout_ground_truth.csv"
    ground_truth.write_text(Path(GROUND_TRUTH_PATH).read_text(), encoding="utf-8")
    temporal_manifest = tmp_path / "v4_temporal_heldout_manifest.json"
    temporal_manifest.write_text(Path(MANIFEST_PATH).read_text(), encoding="utf-8")
    temporal_checksums = tmp_path / "v4_temporal_heldout_checksums.json"
    temporal_payload = json.loads(Path(CHECKSUMS_PATH).read_text())
    temporal_payload["artifacts"] = {
        str(final_events): _sha(final_events),
        str(ground_truth): _sha(ground_truth),
        str(tmp_path / "annotation.csv"): "unused",
        str(temporal_manifest): _sha(temporal_manifest),
    }
    annotation = tmp_path / "annotation.csv"
    annotation.write_text("x\n", encoding="utf-8")
    temporal_payload["artifacts"][str(annotation)] = _sha(annotation)
    temporal_checksums.write_text(json.dumps(temporal_payload), encoding="utf-8")
    freeze_manifest = tmp_path / "v4_final_freeze_manifest.json"
    freeze_manifest.write_text(
        json.dumps(
            {
                "freeze_status": "V4 DEVELOPMENT FROZEN",
                "freeze_timestamp_utc": "2026-08-11T21:00:09+00:00",
                "retrieval": {"top_k": 10},
                "support_policy": {"support_threshold": 2},
                "mechanism_representation": {
                    "transmission_context_version": "transmission_context_v1",
                    "canonical_family_version": "canonical_family_v1",
                    "mechanism_compatibility_version": "mechanism_compatibility_candidate_v1",
                },
            }
        ),
        encoding="utf-8",
    )
    freeze_checksums = tmp_path / "v4_freeze_checksums.json"
    freeze_checksums.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")
    status = tmp_path / "heldout_status.json"
    status.write_text(
        json.dumps(
            {
                "ground_truth_frozen": True,
                "heldout_manifest_sealed": True,
                "predictions_frozen": False,
                "car_run": False,
            }
        ),
        encoding="utf-8",
    )
    import src.validation.v4_temporal_prediction as module

    monkeypatch.setattr(module, "STATUS_PATH", status)
    return {
        "final_events_path": final_events,
        "ground_truth_path": ground_truth,
        "temporal_manifest_path": temporal_manifest,
        "temporal_checksums_path": temporal_checksums,
        "freeze_manifest_path": freeze_manifest,
        "freeze_checksums_path": freeze_checksums,
        "status_path": status,
    }


def _report():
    event = EventAnalysis(
        title="Fixture event",
        summary="Fixture event involving critical minerals and trade restrictions.",
        event_type="fixture",
        regions=["Global"],
        industries=["critical minerals"],
        supply_chain_nodes=["critical_minerals"],
        shock_direction="restriction",
        risk_factors=["trade restriction"],
    )
    retrieved_cases = [
        RetrievedCase(
            case_id="case_fixture",
            title="Fixture case",
            summary="Fixture historical case",
            event_type="fixture",
            supply_chain_nodes=["critical_minerals"],
            transmission_chain=["critical_minerals"],
            relevance="rank=1",
        )
    ]
    chain = TransmissionChain(
        chain_steps=["restriction", "critical_minerals"],
        affected_nodes=["critical_minerals"],
        node_supporting_case_ids={"critical_minerals": ["case_fixture"]},
        node_evidence_levels={"critical_minerals": "event_node"},
        supporting_case_ids=["case_fixture"],
        rationale="fixture",
    )
    asset = CandidateAsset(
        asset_id="ASSET",
        name="Fixture Asset",
        supply_chain_node="critical_minerals",
        ticker="AAA",
        asset_name="Fixture Asset",
        asset_type="Stock",
    )
    evidence = EvidenceResult(
        asset=asset,
        evidence_grade="high",
        rationale="fixture",
        supporting_case_ids=["case_fixture"],
        ticker="AAA",
        asset_name="Fixture Asset",
        evidence_level="historical_supported",
        confidence=0.82,
        reason="fixture",
        transmission_order="second_order",
        priority_tier="high_priority",
        rank_within_order=1,
        ranking_version="ranking_v1",
        ranking_scope="ranked_second_order",
    )
    return FinalReport(
        event=event,
        retrieved_cases=retrieved_cases,
        transmission_chain=chain,
        evidence_results=[evidence],
        summary="fixture",
        event_summary="fixture",
        disclaimer="not investment advice",
    )


def _sha(path):
    import hashlib

    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()
