"""Run frozen V4 predictions for the sealed temporal held-out benchmark.

Prediction generation is separated from ground-truth evaluation. The generation
path reads only sealed event inputs and frozen V4 artifacts. It does not read
prices, returns, CAR outputs, or ground-truth annotations.
"""

from __future__ import annotations

import csv
import hashlib
import json
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.mechanism_context import support_diagnostics
from src.pipeline import run_v4_pipeline
from src.transmission_context_store import (
    load_historical_contexts,
    missing_context,
    project_current_event_context,
)
from src.v4_config import V4_CONFIG, assert_v4_config
from src.validation.v4_temporal_heldout import (
    CHECKSUMS_PATH as TEMPORAL_CHECKSUMS_PATH,
    FINAL_EVENTS_PATH,
    GROUND_TRUTH_PATH,
    MANIFEST_PATH as TEMPORAL_MANIFEST_PATH,
    assert_temporal_heldout_ready_for_prediction,
    sha256_file,
)
from src.validation.v4_heldout_protocol import (
    DEFAULT_FREEZE_CHECKSUMS_PATH,
    DEFAULT_FREEZE_MANIFEST_PATH,
    assert_freeze_manifest_ready,
)


PREDICTION_DIR = Path("data/validation_v4/predictions")
RESULTS_DIR = Path("data/validation_v4/results")
RAW_PREDICTIONS_PATH = PREDICTION_DIR / "v4_temporal_raw_predictions.json"
NODE_SNAPSHOT_PATH = PREDICTION_DIR / "v4_temporal_prediction_snapshot.csv"
ASSET_SNAPSHOT_PATH = PREDICTION_DIR / "v4_temporal_asset_snapshot.csv"
PREDICTION_MANIFEST_PATH = PREDICTION_DIR / "v4_temporal_prediction_manifest.json"
PREDICTION_CHECKSUMS_PATH = PREDICTION_DIR / "v4_temporal_prediction_checksums.json"
MECHANISM_EVALUATION_PATH = RESULTS_DIR / "v4_temporal_mechanism_evaluation.csv"
MECHANISM_SUMMARY_PATH = RESULTS_DIR / "v4_temporal_mechanism_evaluation_summary.json"
ERROR_ANALYSIS_PATH = RESULTS_DIR / "v4_temporal_error_analysis.csv"
STATUS_PATH = Path("data/validation_v4/heldout_status.json")
ATTEMPT_001_ID = "temporal_prediction_attempt_001"
ATTEMPT_002_ID = "temporal_prediction_attempt_002"
ATTEMPT_001_MANIFEST_PATH = (
    Path("data/validation_v4/execution_diagnostics")
    / "temporal_prediction_attempt_001_manifest.json"
)
EXECUTION_FIX_MANIFEST_PATH = (
    Path("data/validation_v4/execution_diagnostics")
    / "v4_post_freeze_execution_fix_manifest.json"
)


def run_and_freeze_temporal_predictions(
    final_events_path: str | Path = FINAL_EVENTS_PATH,
    temporal_manifest_path: str | Path = TEMPORAL_MANIFEST_PATH,
    temporal_checksums_path: str | Path = TEMPORAL_CHECKSUMS_PATH,
    freeze_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
    freeze_checksums_path: str | Path = DEFAULT_FREEZE_CHECKSUMS_PATH,
    prediction_dir: str | Path = PREDICTION_DIR,
    overwrite: bool = False,
    attempt_id: str = ATTEMPT_001_ID,
    parent_attempt: str | None = None,
    retry_reason: str | None = None,
    attempt_type: str = "initial_prediction_attempt",
    allow_controlled_retry_after_frozen: bool = False,
) -> dict[str, Any]:
    """Run frozen V4 once for each sealed temporal event and freeze snapshots."""

    preflight = pre_run_integrity_check(
        temporal_manifest_path=temporal_manifest_path,
        temporal_checksums_path=temporal_checksums_path,
        freeze_manifest_path=freeze_manifest_path,
        freeze_checksums_path=freeze_checksums_path,
        allow_controlled_retry_after_frozen=allow_controlled_retry_after_frozen,
        attempt_id=attempt_id,
        parent_attempt=parent_attempt,
        retry_reason=retry_reason,
    )
    prediction_output = Path(prediction_dir)
    paths = prediction_paths(prediction_output)
    if not overwrite:
        existing = [path for path in paths.values() if path.exists()]
        if existing:
            raise FileExistsError(f"Refusing to overwrite frozen predictions: {existing[0]}")

    events = load_csv(final_events_path)
    raw_predictions: list[dict[str, Any]] = []
    node_rows: list[dict[str, Any]] = []
    asset_rows: list[dict[str, Any]] = []
    success_count = 0
    runtime_failure_count = 0

    for event in events:
        event_id = event["event_id"]
        try:
            report = run_v4_pipeline(event["short_description"], event_analyzer="rule")
            raw_predictions.append(raw_prediction_record(event, report, status="success"))
            node_rows.extend(node_snapshot_rows(event_id, report))
            asset_rows.extend(asset_snapshot_rows(event_id, report))
            success_count += 1
        except Exception as exc:  # pragma: no cover - exercised through failure policy tests.
            raw_predictions.append(
                {
                    "event_id": event_id,
                    "status": "runtime_failure",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "full_traceback": traceback.format_exc(),
                    "input_event": event,
                    "retry_count": 0,
                }
            )
            node_rows.append(runtime_failure_node_row(event_id, type(exc).__name__, str(exc)))
            runtime_failure_count += 1

    prediction_output.mkdir(parents=True, exist_ok=True)
    write_json(paths["raw_predictions"], {
        "attempt_id": attempt_id,
        "parent_attempt": parent_attempt,
        "retry_reason": retry_reason,
        "attempt_type": attempt_type,
        "benchmark_version": "v4_temporal_heldout_v1",
        "ground_truth_accessed_during_generation": False,
        "prices_accessed": False,
        "returns_accessed": False,
        "CAR_run": False,
        "predictions": raw_predictions,
    })
    write_csv(paths["node_snapshot"], node_rows)
    write_csv(paths["asset_snapshot"], asset_rows)
    manifest = build_prediction_manifest(
        selected_event_count=len(events),
        success_count=success_count,
        runtime_failure_count=runtime_failure_count,
        preflight=preflight,
        paths=paths,
        attempt_id=attempt_id,
        parent_attempt=parent_attempt,
        retry_reason=retry_reason,
        attempt_type=attempt_type,
    )
    write_json(paths["prediction_manifest"], manifest)
    checksums = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempt_id": attempt_id,
        "benchmark_version": "v4_temporal_heldout_v1",
        "artifacts": {
            str(paths["raw_predictions"]): sha256_file(paths["raw_predictions"]),
            str(paths["node_snapshot"]): sha256_file(paths["node_snapshot"]),
            str(paths["asset_snapshot"]): sha256_file(paths["asset_snapshot"]),
            str(paths["prediction_manifest"]): sha256_file(paths["prediction_manifest"]),
        },
    }
    write_json(paths["prediction_checksums"], checksums)
    valid_prediction_snapshot_available = success_count > 0
    update_status_predictions_frozen(
        attempt_id=attempt_id,
        attempt_status="completed" if valid_prediction_snapshot_available else "runtime_failure",
        valid_prediction_snapshot_available=valid_prediction_snapshot_available,
    )
    return {
        "attempt_id": attempt_id,
        "parent_attempt": parent_attempt,
        "retry_reason": retry_reason,
        "events_attempted": len(events),
        "successful": success_count,
        "runtime_failures": runtime_failure_count,
        "raw_prediction_artifact": str(paths["raw_predictions"]),
        "node_snapshot": str(paths["node_snapshot"]),
        "asset_snapshot": str(paths["asset_snapshot"]),
        "prediction_manifest": str(paths["prediction_manifest"]),
        "prediction_checksums": str(paths["prediction_checksums"]),
        "predictions_frozen": True,
        "valid_prediction_snapshot_available": valid_prediction_snapshot_available,
        "car_run": False,
    }


def evaluate_frozen_temporal_mechanisms(
    ground_truth_path: str | Path = GROUND_TRUTH_PATH,
    node_snapshot_path: str | Path = NODE_SNAPSHOT_PATH,
    prediction_checksums_path: str | Path = PREDICTION_CHECKSUMS_PATH,
    output_path: str | Path = MECHANISM_EVALUATION_PATH,
    summary_path: str | Path = MECHANISM_SUMMARY_PATH,
    error_path: str | Path = ERROR_ANALYSIS_PATH,
) -> dict[str, Any]:
    """Evaluate frozen node predictions against frozen temporal ground truth."""

    assert_prediction_checksums_valid(prediction_checksums_path)
    ground_truth = load_csv(ground_truth_path)
    node_rows = load_csv(node_snapshot_path)
    predicted_by_key = {(row["event_id"], row["node"]): row for row in node_rows}
    runtime_failure_events = {
        row["event_id"]
        for row in node_rows
        if row.get("predicted_support_status") == "runtime_failure"
    }
    evaluation_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []

    for truth in ground_truth:
        key = (truth["event_id"], truth["node"])
        prediction = predicted_by_key.get(key)
        predicted_class = (
            "runtime_failure"
            if truth["event_id"] in runtime_failure_events
            else predicted_class_for(prediction)
        )
        correct, error_type = evaluate_class(truth["expected_support_class"], predicted_class)
        row = {
            "event_id": truth["event_id"],
            "node": truth["node"],
            "ground_truth_class": truth["expected_support_class"],
            "predicted_class": predicted_class,
            "correct": correct,
            "error_type": error_type,
            "representation_gap_observed": truth.get("representation_gap_observed", "False"),
            "notes": truth.get("review_notes", ""),
        }
        evaluation_rows.append(row)
        if not correct:
            error_rows.append(error_analysis_row(row, prediction))

    write_csv(output_path, evaluation_rows)
    write_csv(error_path, error_rows)
    summary = mechanism_summary(evaluation_rows)
    write_json(summary_path, summary)
    return summary


def pre_run_integrity_check(
    temporal_manifest_path: str | Path = TEMPORAL_MANIFEST_PATH,
    temporal_checksums_path: str | Path = TEMPORAL_CHECKSUMS_PATH,
    freeze_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
    freeze_checksums_path: str | Path = DEFAULT_FREEZE_CHECKSUMS_PATH,
    allow_controlled_retry_after_frozen: bool = False,
    attempt_id: str = ATTEMPT_001_ID,
    parent_attempt: str | None = None,
    retry_reason: str | None = None,
) -> dict[str, Any]:
    """Validate V4 and temporal seals before any prediction execution."""

    assert_v4_config(V4_CONFIG)
    freeze_manifest = assert_freeze_manifest_ready(freeze_manifest_path)
    assert_freeze_checksums_valid(freeze_checksums_path)
    ready = assert_temporal_heldout_ready_for_prediction(
        manifest_path=temporal_manifest_path,
        checksums_path=temporal_checksums_path,
        freeze_manifest_path=freeze_manifest_path,
    )
    status = load_json(STATUS_PATH) if STATUS_PATH.exists() else {}
    if status.get("predictions_frozen") is True and not allow_controlled_retry_after_frozen:
        raise RuntimeError("temporal_prediction_preflight_failed:predictions_already_frozen")
    attempt_001_preserved = False
    execution_fix_valid = False
    if allow_controlled_retry_after_frozen:
        assert_controlled_retry_allowed(
            attempt_id=attempt_id,
            parent_attempt=parent_attempt,
            retry_reason=retry_reason,
        )
        attempt_001_preserved = True
        execution_fix_valid = True
    if status.get("car_run") is True:
        raise RuntimeError("temporal_prediction_preflight_failed:car_already_run")
    temporal_manifest = load_json(temporal_manifest_path)
    if temporal_manifest.get("selected_event_count") != 16:
        raise RuntimeError("temporal_prediction_preflight_failed:selected_event_count")
    if temporal_manifest.get("node_annotation_count") != 32:
        raise RuntimeError("temporal_prediction_preflight_failed:node_annotation_count")
    return {
        "v4_freeze_manifest_valid": True,
        "v4_freeze_checksums_valid": True,
        "temporal_manifest_valid": True,
        "temporal_checksums_valid": True,
        "selected_event_count": ready["selected_event_count"],
        "node_annotation_count": ready["node_annotation_count"],
        "ground_truth_frozen": status.get("ground_truth_frozen") is True,
        "heldout_manifest_sealed": status.get("heldout_manifest_sealed") is True,
        "predictions_frozen_before_run": status.get("predictions_frozen") is True,
        "car_run": False,
        "freeze_timestamp_utc": freeze_manifest.get("freeze_timestamp_utc"),
        "attempt_id": attempt_id,
        "parent_attempt": parent_attempt,
        "retry_reason": retry_reason,
        "attempt_001_preserved": attempt_001_preserved,
        "execution_fix_manifest_valid": execution_fix_valid,
    }


def assert_controlled_retry_allowed(
    attempt_id: str,
    parent_attempt: str | None,
    retry_reason: str | None,
    attempt_manifest_path: str | Path = ATTEMPT_001_MANIFEST_PATH,
    attempt_checksums_path: str | Path = PREDICTION_CHECKSUMS_PATH,
    execution_fix_manifest_path: str | Path = EXECUTION_FIX_MANIFEST_PATH,
) -> None:
    """Validate that a post-freeze prediction retry is execution-only."""

    if attempt_id != ATTEMPT_002_ID:
        raise RuntimeError("controlled_retry_preflight_failed:wrong_attempt_id")
    if parent_attempt != ATTEMPT_001_ID:
        raise RuntimeError("controlled_retry_preflight_failed:wrong_parent_attempt")
    if retry_reason != "execution_client_lifecycle_fix":
        raise RuntimeError("controlled_retry_preflight_failed:wrong_retry_reason")
    attempt_001 = load_json(attempt_manifest_path)
    if attempt_001.get("attempt_id") != ATTEMPT_001_ID:
        raise RuntimeError("controlled_retry_preflight_failed:attempt_001_id")
    if attempt_001.get("attempt_status") != "runtime_failure":
        raise RuntimeError("controlled_retry_preflight_failed:attempt_001_status")
    if attempt_001.get("valid_prediction_snapshot_available") is not False:
        raise RuntimeError("controlled_retry_preflight_failed:attempt_001_valid_snapshot")
    assert_prediction_checksums_valid(attempt_checksums_path)
    fix_manifest = load_json(execution_fix_manifest_path)
    if fix_manifest.get("original_attempt") != ATTEMPT_001_ID:
        raise RuntimeError("controlled_retry_preflight_failed:fix_original_attempt")
    if fix_manifest.get("retry_approved") is not True:
        raise RuntimeError("controlled_retry_preflight_failed:retry_not_approved")
    for key in [
        "semantic_config_changed",
        "benchmark_changed",
        "ground_truth_changed",
        "representation_changed",
        "market_data_accessed",
    ]:
        if fix_manifest.get(key) is not False:
            raise RuntimeError(f"controlled_retry_preflight_failed:{key}")


def assert_freeze_checksums_valid(path: str | Path = DEFAULT_FREEZE_CHECKSUMS_PATH) -> None:
    """Validate frozen V4 artifact checksums."""

    payload = load_json(path)
    failed = [
        artifact
        for artifact, expected in payload.get("artifacts", {}).items()
        if Path(artifact).exists() and sha256_file(artifact) != expected
    ]
    if failed:
        raise RuntimeError(f"v4_freeze_checksum_mismatch:{','.join(failed)}")


def assert_prediction_checksums_valid(path: str | Path = PREDICTION_CHECKSUMS_PATH) -> None:
    """Validate frozen prediction snapshot checksums."""

    payload = load_json(path)
    failed = [
        artifact
        for artifact, expected in payload.get("artifacts", {}).items()
        if sha256_file(artifact) != expected
    ]
    if failed:
        raise RuntimeError(f"prediction_checksum_mismatch:{','.join(failed)}")


def raw_prediction_record(event: dict[str, str], report: Any, status: str) -> dict[str, Any]:
    """Serialize the raw report plus frozen identifiers for one event."""

    return {
        "event_id": event["event_id"],
        "status": status,
        "input_event": event,
        "v4_config": {
            "top_k": V4_CONFIG.retrieval_top_k,
            "mechanism_compatible_support": V4_CONFIG.use_mechanism_compatible_support,
            "support_threshold": V4_CONFIG.compatible_support_threshold,
            "transmission_context_version": V4_CONFIG.transmission_context_version,
            "canonical_family_version": V4_CONFIG.canonical_family_version,
            "mechanism_compatibility_version": V4_CONFIG.mechanism_compatibility_version,
            "asset_ranker_version": V4_CONFIG.asset_ranker_version,
        },
        "report": report.model_dump(mode="json"),
    }


def node_snapshot_rows(event_id: str, report: Any) -> list[dict[str, Any]]:
    """Create node-level prediction snapshot rows from one FinalReport."""

    historical_contexts = load_historical_contexts()
    rows: list[dict[str, Any]] = []
    event_nodes = set(report.event.supply_chain_nodes)
    affected_nodes = list(report.transmission_chain.affected_nodes)
    support_map = dict(report.transmission_chain.node_supporting_case_ids)
    for node in affected_nodes:
        case_ids = support_map.get(node, [])
        current_context = project_current_event_context(report.event, node)
        supporting_contexts = [
            {"case_id": case_id, **historical_contexts.get((case_id, node), missing_context(node))}
            for case_id in case_ids
        ]
        diagnostics = support_diagnostics(current_context, supporting_contexts)
        predicted_status = "accepted_first_order" if node in event_nodes else "accepted_second_order"
        insufficient_context = (
            bool(case_ids)
            and diagnostics["insufficient_context_count"] > 0
            and diagnostics["compatible_support_count"] == 0
        )
        rows.append(
            {
                "event_id": event_id,
                "node": node,
                "predicted_support_status": predicted_status,
                "compatible_support_count": diagnostics["compatible_support_count"],
                "exact_support_count": diagnostics["exact_support_count"],
                "canonical_family_support_count": diagnostics["canonical_family_support_count"],
                "insufficient_context": insufficient_context,
                "supporting_case_ids": json.dumps(case_ids, sort_keys=True),
                "retrieval_ranks": json.dumps(case_retrieval_ranks(report, case_ids), sort_keys=True),
                "mechanism_match_types": json.dumps(match_types(diagnostics), sort_keys=True),
                "predicted_evidence_label": report.transmission_chain.node_evidence_levels.get(node, "unknown"),
                "representation_gap_flag_if_runtime_observed": insufficient_context,
                "runtime_status": "success",
            }
        )
    return rows


def asset_snapshot_rows(event_id: str, report: Any) -> list[dict[str, Any]]:
    """Create asset-level frozen snapshot rows."""

    rows = []
    for result in report.evidence_results:
        rows.append(
            {
                "event_id": event_id,
                "asset": result.ticker,
                "node": result.asset.supply_chain_node or "unknown",
                "rank": result.rank_within_order,
                "evidence_label": result.evidence_level,
                "confidence": result.confidence,
                "transmission_order": result.transmission_order,
                "priority_tier": result.priority_tier,
                "ranking_scope": result.ranking_scope,
                "ranking_version": result.ranking_version,
                "predicted_direction_if_pipeline_already_outputs_it": "",
            }
        )
    return rows


def runtime_failure_node_row(event_id: str, error_type: str, error: str) -> dict[str, Any]:
    """Return a node-snapshot row for runtime failure."""

    return {
        "event_id": event_id,
        "node": "__runtime_failure__",
        "predicted_support_status": "runtime_failure",
        "compatible_support_count": 0,
        "exact_support_count": 0,
        "canonical_family_support_count": 0,
        "insufficient_context": False,
        "supporting_case_ids": "[]",
        "retrieval_ranks": "{}",
        "mechanism_match_types": "{}",
        "predicted_evidence_label": error_type,
        "representation_gap_flag_if_runtime_observed": False,
        "runtime_status": error,
    }


def build_prediction_manifest(
    selected_event_count: int,
    success_count: int,
    runtime_failure_count: int,
    preflight: dict[str, Any],
    paths: dict[str, Path],
    attempt_id: str = ATTEMPT_001_ID,
    parent_attempt: str | None = None,
    retry_reason: str | None = None,
    attempt_type: str = "initial_prediction_attempt",
) -> dict[str, Any]:
    """Build prediction-run manifest after all events are processed."""

    return {
        "attempt_id": attempt_id,
        "parent_attempt": parent_attempt,
        "retry_reason": retry_reason,
        "attempt_type": attempt_type,
        "benchmark_version": "v4_temporal_heldout_v1",
        "prediction_run_timestamp": datetime.now(timezone.utc).isoformat(),
        "selected_event_count": selected_event_count,
        "success_count": success_count,
        "runtime_failure_count": runtime_failure_count,
        "v4_config": {
            "top_k": V4_CONFIG.retrieval_top_k,
            "mechanism_compatible_support": V4_CONFIG.use_mechanism_compatible_support,
            "support_threshold": V4_CONFIG.compatible_support_threshold,
            "transmission_context_version": V4_CONFIG.transmission_context_version,
            "canonical_family_version": V4_CONFIG.canonical_family_version,
            "mechanism_compatibility_version": V4_CONFIG.mechanism_compatibility_version,
            "asset_ranker_version": V4_CONFIG.asset_ranker_version,
        },
        "preflight": preflight,
        "execution_fix_reference": str(EXECUTION_FIX_MANIFEST_PATH)
        if attempt_id == ATTEMPT_002_ID
        else "",
        "raw_prediction_artifact": str(paths["raw_predictions"]),
        "node_snapshot_path": str(paths["node_snapshot"]),
        "asset_snapshot_path": str(paths["asset_snapshot"]),
        "ground_truth_accessed_during_generation": False,
        "prices_accessed": False,
        "returns_accessed": False,
        "CAR_run": False,
        "semantic_config_changed": False,
        "benchmark_changed": False,
        "ground_truth_changed": False,
    }


def predicted_class_for(prediction: dict[str, str] | None) -> str:
    """Map node snapshot row into frozen evaluation class."""

    if prediction is None:
        return "rejected"
    if prediction.get("predicted_support_status") == "runtime_failure":
        return "runtime_failure"
    if str(prediction.get("insufficient_context")) == "True":
        return "insufficient_context_predicted"
    if prediction.get("predicted_support_status", "").startswith("accepted"):
        return "compatible_support_predicted"
    return "rejected"


def evaluate_class(ground_truth: str, predicted: str) -> tuple[bool, str]:
    """Return correctness and error type for one annotation."""

    if predicted == "runtime_failure":
        return False, "runtime_failure"
    if ground_truth == "compatible_support_expected":
        if predicted == "compatible_support_predicted":
            return True, ""
        return False, "false_rejection"
    if ground_truth == "weak_cooccurrence_expected":
        if predicted in {"rejected", "insufficient_context_predicted"}:
            return True, ""
        return False, "false_acceptance"
    if ground_truth == "insufficient_context_expected":
        if predicted in {"insufficient_context_predicted", "rejected"}:
            return True, ""
        return False, "incorrect_insufficient_handling"
    return False, "unknown_ground_truth_class"


def mechanism_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize frozen temporal mechanism evaluation."""

    total = len(rows)
    by_truth = Counter(row["ground_truth_class"] for row in rows)
    errors = Counter(row["error_type"] for row in rows if row["error_type"])
    compatible_total = by_truth["compatible_support_expected"]
    weak_total = by_truth["weak_cooccurrence_expected"]
    insufficient_total = by_truth["insufficient_context_expected"]
    compatible_retained = sum(
        row["ground_truth_class"] == "compatible_support_expected" and row["correct"] is True
        for row in rows
    )
    weak_rejected = sum(
        row["ground_truth_class"] == "weak_cooccurrence_expected" and row["correct"] is True
        for row in rows
    )
    insufficient_correct = sum(
        row["ground_truth_class"] == "insufficient_context_expected" and row["correct"] is True
        for row in rows
    )
    representation_gap_rows = [
        row for row in rows if str(row.get("representation_gap_observed")) == "True"
    ]
    return {
        "total_annotations": total,
        "compatible_total": compatible_total,
        "compatible_retained": compatible_retained,
        "compatible_retention_rate": rate(compatible_retained, compatible_total),
        "weak_total": weak_total,
        "weak_rejected": weak_rejected,
        "weak_rejection_rate": rate(weak_rejected, weak_total),
        "weak_leakage": errors["false_acceptance"],
        "weak_leakage_rate": rate(errors["false_acceptance"], weak_total),
        "insufficient_total": insufficient_total,
        "correct_insufficient": insufficient_correct,
        "insufficient_handling_rate": rate(insufficient_correct, insufficient_total),
        "false_rejection": errors["false_rejection"],
        "false_acceptance": errors["false_acceptance"],
        "runtime_failure": errors["runtime_failure"],
        "error_counts": dict(errors),
        "representation_gap_total": len(representation_gap_rows),
        "representation_gap_correct": sum(row["correct"] is True for row in representation_gap_rows),
        "prices_accessed": False,
        "CAR_run": False,
    }


def error_analysis_row(row: dict[str, Any], prediction: dict[str, str] | None) -> dict[str, Any]:
    """Classify held-out errors without changing V4."""

    if row["error_type"] == "runtime_failure":
        taxonomy = "runtime_failure"
    elif str(row.get("representation_gap_observed")) == "True":
        taxonomy = "known_vocabulary_gap"
    elif prediction is None:
        taxonomy = "retrieval_gap"
    elif row["error_type"] == "false_acceptance":
        taxonomy = "historical_context_gap"
    else:
        taxonomy = "other"
    return {
        "event_id": row["event_id"],
        "node": row["node"],
        "ground_truth_class": row["ground_truth_class"],
        "predicted_class": row["predicted_class"],
        "error_type": row["error_type"],
        "error_taxonomy": taxonomy,
        "post_freeze_v5_candidate_issue": True,
        "notes": "Recorded after V4 freeze; do not modify V4 from this result.",
    }


def match_types(diagnostics: dict[str, Any]) -> dict[str, list[str]]:
    """Map match type to supporting case ids."""

    result: dict[str, list[str]] = {}
    for decision in diagnostics.get("case_decisions", []):
        if decision.get("status") != "compatible":
            continue
        result.setdefault(str(decision.get("match_type")), []).append(str(decision.get("case_id")))
    return result


def case_retrieval_ranks(report: Any, case_ids: list[str]) -> dict[str, int]:
    """Return one-based retrieval ranks for supporting case ids."""

    rank_by_case = {case.case_id: idx for idx, case in enumerate(report.retrieved_cases, start=1)}
    return {case_id: rank_by_case.get(case_id, 0) for case_id in case_ids}


def update_status_predictions_frozen(
    path: Path | None = None,
    attempt_id: str = ATTEMPT_001_ID,
    attempt_status: str = "completed",
    valid_prediction_snapshot_available: bool = True,
) -> None:
    """Mark predictions frozen without marking CAR run."""

    status_path = path or STATUS_PATH
    status = load_json(status_path) if status_path.exists() else {}
    status.update(
        {
            "candidate_pool_created": True,
            "heldout_events_created": True,
            "ground_truth_frozen": True,
            "heldout_manifest_sealed": True,
            "predictions_frozen": True,
            "latest_prediction_attempt": attempt_id,
            f"{attempt_id}_frozen": True,
            f"{attempt_id}_status": attempt_status,
            "valid_prediction_snapshot_available": valid_prediction_snapshot_available,
            "price_inputs_prepared": False,
            "car_run": False,
        }
    )
    write_json(status_path, status)


def prediction_paths(base: Path) -> dict[str, Path]:
    """Return prediction artifact paths under a base directory."""

    return {
        "raw_predictions": base / RAW_PREDICTIONS_PATH.name,
        "node_snapshot": base / NODE_SNAPSHOT_PATH.name,
        "asset_snapshot": base / ASSET_SNAPSHOT_PATH.name,
        "prediction_manifest": base / PREDICTION_MANIFEST_PATH.name,
        "prediction_checksums": base / PREDICTION_CHECKSUMS_PATH.name,
    }


def load_csv(path: str | Path) -> list[dict[str, str]]:
    """Load CSV rows."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [{key: (value or "") for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write CSV rows, creating an empty placeholder if needed."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["empty"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return output


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write stable JSON."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON object."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def rate(numerator: int, denominator: int) -> float | None:
    """Return a rounded rate or None for zero denominator."""

    if denominator == 0:
        return None
    return round(numerator / denominator, 6)
