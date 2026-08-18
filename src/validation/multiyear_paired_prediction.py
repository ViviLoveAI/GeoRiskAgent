"""Run frozen V3/V4 multi-year paired predictions and derived evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.mechanism_context import support_diagnostics
from src.pipeline import run_v3_pipeline, run_v4_pipeline
from src.transmission_context_store import (
    load_historical_contexts,
    missing_context,
    project_current_event_context,
)
from src.v3_config import V3_CONFIG, assert_v3_config
from src.v4_config import V4_CONFIG, assert_v4_config
from src.validation.multiyear_general_benchmark import (
    CHECKSUMS_PATH,
    FINAL_EVENTS_PATH,
    GROUND_TRUTH_PATH,
    MANIFEST_PATH,
    assert_multiyear_ready_for_prediction,
)
from src.validation.v4_heldout_protocol import DEFAULT_FREEZE_CHECKSUMS_PATH
from src.v4_config import POST_FREEZE_FIX_MANIFEST


OUTPUT_DIR = Path("data/validation_general")
PREDICTION_DIR = OUTPUT_DIR / "predictions"
RESULTS_DIR = OUTPUT_DIR / "results"
V3_PREDICTION_DIR = PREDICTION_DIR / "v3"
V4_PREDICTION_DIR = PREDICTION_DIR / "v4"
COMPARISON_PATH = RESULTS_DIR / "v3_v4_paired_node_comparison.csv"
SUMMARY_PATH = RESULTS_DIR / "v3_v4_paired_evaluation_summary.json"
POST_FREEZE_PRODUCTION_FIX_PATH = Path(POST_FREEZE_FIX_MANIFEST)


def run_and_evaluate_multiyear_paired_predictions(
    overwrite: bool = False,
) -> dict[str, Any]:
    """Run frozen V3 and V4 predictions, seal snapshots, then evaluate."""

    preflight = pre_run_integrity_check()
    v3_result = run_and_freeze_system_predictions(
        system="v3",
        runner=run_v3_pipeline,
        prediction_dir=V3_PREDICTION_DIR,
        overwrite=overwrite,
        preflight=preflight,
    )
    v4_result = run_and_freeze_system_predictions(
        system="v4",
        runner=lambda text: run_v4_pipeline(text, event_analyzer="rule"),
        prediction_dir=V4_PREDICTION_DIR,
        overwrite=overwrite,
        preflight=preflight,
    )
    evaluation = evaluate_paired_predictions()
    return {"v3_prediction": v3_result, "v4_prediction": v4_result, "evaluation": evaluation}


def pre_run_integrity_check() -> dict[str, Any]:
    """Validate frozen V3/V4 and sealed benchmark before prediction."""

    assert_v3_config(V3_CONFIG)
    assert_v4_config(V4_CONFIG)
    ready = assert_multiyear_ready_for_prediction()
    assert_flat_or_wrapped_checksums_valid(DEFAULT_FREEZE_CHECKSUMS_PATH)
    events = load_csv(FINAL_EVENTS_PATH)
    truth = load_csv(GROUND_TRUTH_PATH)
    if len(events) != 23:
        raise RuntimeError(f"multiyear_prediction_preflight_failed:event_count:{len(events)}")
    if len(truth) != 46:
        raise RuntimeError(f"multiyear_prediction_preflight_failed:annotation_count:{len(truth)}")
    return {
        "v3_manifest_checksums_valid": True,
        "v4_manifest_checksums_valid": True,
        "multiyear_manifest_checksums_valid": True,
        "selected_event_count": len(events),
        "node_annotation_count": len(truth),
        "ground_truth_frozen": True,
        "prices_accessed": False,
        "CAR_run": False,
        **ready,
    }


def run_and_freeze_system_predictions(
    system: str,
    runner: Callable[[str], Any],
    prediction_dir: str | Path,
    overwrite: bool,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    """Run one frozen system across the sealed multi-year events."""

    output = Path(prediction_dir)
    paths = prediction_paths(output)
    if not overwrite:
        existing = [path for path in paths.values() if path.exists()]
        if existing:
            raise FileExistsError(f"Refusing to overwrite frozen {system} predictions: {existing[0]}")

    events = load_csv(FINAL_EVENTS_PATH)
    raw_predictions = []
    node_rows = []
    asset_rows = []
    success_count = 0
    failure_count = 0
    for event in events:
        event_id = event["candidate_id"]
        try:
            report = runner(event["short_preoutcome_description"])
            raw_predictions.append(raw_prediction_record(system, event, report, "success"))
            node_rows.extend(node_snapshot_rows(system, event_id, report))
            asset_rows.extend(asset_snapshot_rows(system, event_id, report))
            success_count += 1
        except Exception as exc:  # pragma: no cover
            raw_predictions.append(
                {
                    "system": system,
                    "event_id": event_id,
                    "status": "runtime_failure",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "full_traceback": traceback.format_exc(),
                    "input_event": event,
                }
            )
            node_rows.append(runtime_failure_node_row(system, event_id, type(exc).__name__, str(exc)))
            failure_count += 1

    output.mkdir(parents=True, exist_ok=True)
    write_json(paths["raw_predictions"], {
        "system": system,
        "benchmark_version": "georisk_multiyear_general_v1",
        "ground_truth_accessed_during_generation": False,
        "prices_accessed": False,
        "returns_accessed": False,
        "CAR_run": False,
        "predictions": raw_predictions,
    })
    write_csv(paths["node_snapshot"], node_rows)
    write_csv(paths["asset_snapshot"], asset_rows)
    manifest = prediction_manifest(system, paths, preflight, len(events), success_count, failure_count)
    write_json(paths["prediction_manifest"], manifest)
    checksums = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "system": system,
        "benchmark_version": "georisk_multiyear_general_v1",
        "artifacts": {str(path): sha256_file(path) for path in paths.values() if path.name != "prediction_checksums.json"},
    }
    write_json(paths["prediction_checksums"], checksums)
    return {
        "system": system,
        "events_attempted": len(events),
        "successful": success_count,
        "runtime_failures": failure_count,
        "raw_prediction_artifact": str(paths["raw_predictions"]),
        "node_snapshot": str(paths["node_snapshot"]),
        "asset_snapshot": str(paths["asset_snapshot"]),
        "prediction_manifest": str(paths["prediction_manifest"]),
        "prediction_checksums": str(paths["prediction_checksums"]),
    }


def evaluate_paired_predictions(
    ground_truth_path: str | Path = GROUND_TRUTH_PATH,
    v3_node_snapshot_path: str | Path = V3_PREDICTION_DIR / "node_snapshot.csv",
    v4_node_snapshot_path: str | Path = V4_PREDICTION_DIR / "node_snapshot.csv",
    v3_checksums_path: str | Path = V3_PREDICTION_DIR / "prediction_checksums.json",
    v4_checksums_path: str | Path = V4_PREDICTION_DIR / "prediction_checksums.json",
    output_path: str | Path = COMPARISON_PATH,
    summary_path: str | Path = SUMMARY_PATH,
) -> dict[str, Any]:
    """Evaluate sealed V3/V4 node snapshots against frozen ground truth."""

    assert_prediction_checksums_valid(v3_checksums_path)
    assert_prediction_checksums_valid(v4_checksums_path)
    truth_rows = load_csv(ground_truth_path)
    v3_by_key = {(row["event_id"], row["node"]): row for row in load_csv(v3_node_snapshot_path)}
    v4_by_key = {(row["event_id"], row["node"]): row for row in load_csv(v4_node_snapshot_path)}

    comparison_rows = []
    for truth in truth_rows:
        key = (truth["event_id"], truth["node"])
        v3 = v3_by_key.get(key)
        v4 = v4_by_key.get(key)
        v3_eval = evaluate_prediction(truth["expected_support_class"], v3)
        v4_eval = evaluate_prediction(truth["expected_support_class"], v4)
        comparison_rows.append(
            {
                "event_id": truth["event_id"],
                "node": truth["node"],
                "ground_truth_class": truth["expected_support_class"],
                "representation_gap_observed": truth["representation_gap_observed"],
                "v3_node_present": v3_eval["node_present"],
                "v3_support_decision": v3_eval["support_decision"],
                "v3_correct": v3_eval["correct"],
                "v4_node_present": v4_eval["node_present"],
                "v4_support_decision": v4_eval["support_decision"],
                "v4_correct": v4_eval["correct"],
                "transition_type": transition_type(v3_eval["correct"], v4_eval["correct"]),
                "error_type_v3": v3_eval["error_type"],
                "error_type_v4": v4_eval["error_type"],
            }
        )
    write_csv(output_path, comparison_rows)
    summary = build_evaluation_summary(comparison_rows)
    write_json(summary_path, summary)
    return summary


def raw_prediction_record(system: str, event: dict[str, str], report: Any, status: str) -> dict[str, Any]:
    """Serialize raw report for one system/event."""

    return {
        "system": system,
        "event_id": event["candidate_id"],
        "status": status,
        "input_event": event,
        "config": system_config(system),
        "report": report.model_dump(mode="json"),
    }


def node_snapshot_rows(system: str, event_id: str, report: Any) -> list[dict[str, Any]]:
    """Serialize one row per final affected node."""

    rows = []
    event_nodes = set(report.event.supply_chain_nodes)
    support_map = dict(report.transmission_chain.node_supporting_case_ids)
    for node in report.transmission_chain.affected_nodes:
        case_ids = support_map.get(node, [])
        diagnostics = support_counts(system, report, node, case_ids)
        rows.append(
            {
                "system": system,
                "event_id": event_id,
                "node": node,
                "node_present": True,
                "node_proposal_source": "event_analyst" if node in event_nodes else "transmission_builder",
                "support_decision": diagnostics["support_decision"],
                "raw_same_node_support_count": diagnostics["raw_same_node_support_count"],
                "compatible_support_count": diagnostics["compatible_support_count"],
                "exact_support_count": diagnostics["exact_support_count"],
                "canonical_family_support_count": diagnostics["canonical_family_support_count"],
                "supporting_case_ids": json.dumps(case_ids, sort_keys=True),
                "retrieval_ranks": json.dumps(case_retrieval_ranks(report, case_ids), sort_keys=True),
                "predicted_evidence_label": report.transmission_chain.node_evidence_levels.get(node, "unknown"),
                "runtime_status": "success",
            }
        )
    return rows


def support_counts(system: str, report: Any, node: str, case_ids: list[str]) -> dict[str, Any]:
    """Return system-specific strict historical support counts."""

    if system == "v3":
        raw_count = len(set(case_ids))
        return {
            "support_decision": raw_count >= V3_CONFIG.support_threshold,
            "raw_same_node_support_count": raw_count,
            "compatible_support_count": 0,
            "exact_support_count": 0,
            "canonical_family_support_count": 0,
        }
    historical_contexts = load_historical_contexts()
    current_context = project_current_event_context(report.event, node)
    supporting_contexts = [
        {"case_id": case_id, **historical_contexts.get((case_id, node), missing_context(node))}
        for case_id in case_ids
    ]
    diagnostics = support_diagnostics(current_context, supporting_contexts)
    return {
        "support_decision": diagnostics["compatible_support_count"] >= V4_CONFIG.compatible_support_threshold,
        "raw_same_node_support_count": len(set(case_ids)),
        "compatible_support_count": diagnostics["compatible_support_count"],
        "exact_support_count": diagnostics["exact_support_count"],
        "canonical_family_support_count": diagnostics["canonical_family_support_count"],
    }


def asset_snapshot_rows(system: str, event_id: str, report: Any) -> list[dict[str, Any]]:
    """Serialize asset rows without market outcomes."""

    rows = []
    for result in report.evidence_results:
        rows.append(
            {
                "system": system,
                "event_id": event_id,
                "node": result.asset.supply_chain_node or "unknown",
                "asset": result.ticker,
                "rank": result.rank_within_order,
                "evidence_label": result.evidence_level,
                "confidence": result.confidence,
                "transmission_order": result.transmission_order,
                "predicted_direction": "",
            }
        )
    return rows


def runtime_failure_node_row(system: str, event_id: str, error_type: str, error: str) -> dict[str, Any]:
    """Return one runtime failure row."""

    return {
        "system": system,
        "event_id": event_id,
        "node": "__runtime_failure__",
        "node_present": False,
        "node_proposal_source": "runtime_failure",
        "support_decision": False,
        "raw_same_node_support_count": 0,
        "compatible_support_count": 0,
        "exact_support_count": 0,
        "canonical_family_support_count": 0,
        "supporting_case_ids": "[]",
        "retrieval_ranks": "{}",
        "predicted_evidence_label": error_type,
        "runtime_status": error,
    }


def evaluate_prediction(ground_truth_class: str, row: dict[str, str] | None) -> dict[str, Any]:
    """Evaluate one system row against one node annotation."""

    node_present = row is not None and row.get("node_present") == "True"
    support_decision = row is not None and row.get("support_decision") == "True"
    if ground_truth_class == "compatible_support_expected":
        correct = node_present
        error = "" if correct else "false_rejection"
    elif ground_truth_class == "weak_cooccurrence_expected":
        correct = not support_decision
        error = "" if correct else "false_acceptance"
    elif ground_truth_class == "insufficient_context_expected":
        correct = not support_decision
        error = "" if correct else "incorrect_insufficient_handling"
    else:
        correct = False
        error = "unknown_ground_truth_class"
    return {
        "node_present": node_present,
        "support_decision": support_decision,
        "correct": correct,
        "error_type": error,
    }


def build_evaluation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build all, representation-gap, and class-stratified paired metrics."""

    return {
        "benchmark_version": "georisk_multiyear_general_v1",
        "total_annotations": len(rows),
        "all": metric_block(rows),
        "representation_gap_false": metric_block(
            [row for row in rows if str(row["representation_gap_observed"]) == "False"]
        ),
        "representation_gap_true": metric_block(
            [row for row in rows if str(row["representation_gap_observed"]) == "True"]
        ),
        "by_ground_truth_class": {
            klass: metric_block([row for row in rows if row["ground_truth_class"] == klass])
            for klass in [
                "compatible_support_expected",
                "weak_cooccurrence_expected",
                "insufficient_context_expected",
            ]
        },
        "transition_counts": dict(Counter(row["transition_type"] for row in rows)),
        "prices_accessed": False,
        "returns_accessed": False,
        "CAR_run": False,
    }


def metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute registered paired metrics for a row subset."""

    compatible = [row for row in rows if row["ground_truth_class"] == "compatible_support_expected"]
    weak = [row for row in rows if row["ground_truth_class"] == "weak_cooccurrence_expected"]
    insufficient = [row for row in rows if row["ground_truth_class"] == "insufficient_context_expected"]
    return {
        "n": len(rows),
        "v3": system_metrics(rows, compatible, weak, insufficient, "v3"),
        "v4": system_metrics(rows, compatible, weak, insufficient, "v4"),
        "delta_v4_minus_v3": delta_metrics(
            system_metrics(rows, compatible, weak, insufficient, "v3"),
            system_metrics(rows, compatible, weak, insufficient, "v4"),
        ),
        "transitions": dict(Counter(row["transition_type"] for row in rows)),
    }


def system_metrics(
    rows: list[dict[str, Any]],
    compatible: list[dict[str, Any]],
    weak: list[dict[str, Any]],
    insufficient: list[dict[str, Any]],
    prefix: str,
) -> dict[str, Any]:
    """Compute metrics for one system."""

    node_presence = sum(row[f"{prefix}_node_present"] is True for row in compatible)
    support_recall = sum(row[f"{prefix}_support_decision"] is True for row in compatible)
    weak_rejected = sum(row[f"{prefix}_support_decision"] is not True for row in weak)
    weak_leakage = sum(row[f"{prefix}_support_decision"] is True for row in weak)
    insufficient_handled = sum(row[f"{prefix}_support_decision"] is not True for row in insufficient)
    correct = sum(row[f"{prefix}_correct"] is True for row in rows)
    return {
        "correct": correct,
        "accuracy": rate(correct, len(rows)),
        "node_presence_recall": rate(node_presence, len(compatible)),
        "node_presence_count": node_presence,
        "support_recall": rate(support_recall, len(compatible)),
        "support_recall_count": support_recall,
        "weak_rejection": rate(weak_rejected, len(weak)),
        "weak_rejection_count": weak_rejected,
        "weak_leakage": rate(weak_leakage, len(weak)),
        "weak_leakage_count": weak_leakage,
        "false_acceptance": weak_leakage,
        "false_rejection": sum(
            row["ground_truth_class"] == "compatible_support_expected"
            and row[f"{prefix}_node_present"] is not True
            for row in rows
        ),
        "insufficient_handling": rate(insufficient_handled, len(insufficient)),
        "insufficient_handling_count": insufficient_handled,
    }


def delta_metrics(v3: dict[str, Any], v4: dict[str, Any]) -> dict[str, Any]:
    """Return V4 minus V3 deltas for rate metrics."""

    keys = [
        "accuracy",
        "node_presence_recall",
        "support_recall",
        "weak_rejection",
        "weak_leakage",
        "insufficient_handling",
    ]
    return {
        key: None if v3[key] is None or v4[key] is None else round(v4[key] - v3[key], 6)
        for key in keys
    }


def transition_type(v3_correct: bool, v4_correct: bool) -> str:
    """Return paired transition label."""

    if v3_correct and v4_correct:
        return "V3_correct_to_V4_correct"
    if not v3_correct and v4_correct:
        return "V3_wrong_to_V4_correct"
    if v3_correct and not v4_correct:
        return "V3_correct_to_V4_wrong"
    return "V3_wrong_to_V4_wrong"


def prediction_manifest(
    system: str,
    paths: dict[str, Path],
    preflight: dict[str, Any],
    events_attempted: int,
    success_count: int,
    runtime_failure_count: int,
) -> dict[str, Any]:
    """Build prediction manifest for one system."""

    return {
        "system": system,
        "benchmark_version": "georisk_multiyear_general_v1",
        "prediction_run_timestamp": datetime.now(timezone.utc).isoformat(),
        "events_attempted": events_attempted,
        "success_count": success_count,
        "runtime_failure_count": runtime_failure_count,
        "config": system_config(system),
        "preflight": preflight,
        "raw_prediction_artifact": str(paths["raw_predictions"]),
        "node_snapshot_path": str(paths["node_snapshot"]),
        "asset_snapshot_path": str(paths["asset_snapshot"]),
        "ground_truth_accessed_during_generation": False,
        "prices_accessed": False,
        "returns_accessed": False,
        "CAR_run": False,
    }


def system_config(system: str) -> dict[str, Any]:
    """Return frozen config identifiers for a system."""

    if system == "v3":
        return {
            "baseline_version": V3_CONFIG.baseline_version,
            "event_analyzer": V3_CONFIG.event_analyzer,
            "top_k": V3_CONFIG.retrieval_top_k,
            "support_threshold": V3_CONFIG.support_threshold,
            "TransmissionContext_enabled": False,
            "mechanism_compatibility_enabled": False,
            "canonical_family_enabled": False,
        }
    return {
        "version": V4_CONFIG.version,
        "event_analyzer": "rule",
        "top_k": V4_CONFIG.retrieval_top_k,
        "support_threshold": V4_CONFIG.compatible_support_threshold,
        "TransmissionContext": V4_CONFIG.transmission_context_version,
        "canonical_family": V4_CONFIG.canonical_family_version,
        "mechanism_compatibility": V4_CONFIG.mechanism_compatibility_version,
        "mechanism_compatible_support": V4_CONFIG.use_mechanism_compatible_support,
    }


def prediction_paths(base: Path) -> dict[str, Path]:
    """Return artifact paths for one prediction directory."""

    return {
        "raw_predictions": base / "raw_predictions.json",
        "node_snapshot": base / "node_snapshot.csv",
        "asset_snapshot": base / "asset_snapshot.csv",
        "prediction_manifest": base / "prediction_manifest.json",
        "prediction_checksums": base / "prediction_checksums.json",
    }


def assert_prediction_checksums_valid(path: str | Path) -> None:
    """Validate prediction checksums."""

    payload = load_json(path)
    failed = [
        artifact
        for artifact, expected in payload.get("artifacts", {}).items()
        if sha256_file(artifact) != expected
    ]
    if failed:
        raise RuntimeError(f"prediction_checksum_mismatch:{','.join(failed)}")


def assert_flat_or_wrapped_checksums_valid(path: str | Path) -> None:
    """Validate frozen checksums while honoring declared production fixes.

    Frozen evaluation artifacts, manifests, configs, and methodology files must
    still match their sealed hashes. Current production implementation files may
    differ only when explicitly declared in the post-freeze production-fix
    manifest and marked as non-methodology, non-artifact changes.
    """

    payload = load_json(path)
    artifacts = payload.get("artifacts", payload)
    declared_post_freeze_files = _declared_post_freeze_production_files()
    failed = [
        artifact
        for artifact, expected in artifacts.items()
        if Path(artifact).exists() and sha256_file(artifact) != expected
        and not _is_declared_post_freeze_file(artifact, declared_post_freeze_files)
    ]
    if failed:
        raise RuntimeError(f"checksum_mismatch:{','.join(failed)}")


def _declared_post_freeze_production_files(
    manifest_path: str | Path | None = None,
) -> set[str]:
    """Return production files covered by the post-freeze fix manifest."""

    path = Path(manifest_path or POST_FREEZE_PRODUCTION_FIX_PATH)
    if not path.exists():
        return set()
    manifest = load_json(path)
    if manifest.get("manifest_id") != "v4_post_freeze_production_fix_manifest":
        return set()
    if manifest.get("methodology_version") != "V4":
        return set()
    if manifest.get("production_version") != "V4.1":
        return set()
    for key in [
        "frozen_evaluation_artifacts_regenerated",
        "frozen_evaluation_metrics_changed",
        "downstream_methodology_changed",
        "retrieval_config_changed",
        "support_policy_changed",
        "ranking_algorithm_changed",
        "evidence_grading_semantics_changed",
        "historical_kb_changed",
        "asset_mapping_semantics_changed",
    ]:
        if manifest.get(key) is not False:
            return set()

    return {
        _artifact_key(path)
        for path in manifest.get("declared_post_freeze_production_files", [])
        if _is_production_implementation_file(str(path))
    }


def _artifact_key(path: str | Path) -> str:
    """Normalize checksum artifact paths for manifest comparison."""

    artifact = Path(path)
    try:
        return artifact.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def _is_declared_post_freeze_file(
    artifact: str | Path,
    declared_files: set[str],
) -> bool:
    """Return true when an artifact matches a declared production file."""

    key = _artifact_key(artifact)
    if key in declared_files:
        return True
    artifact_text = str(artifact)
    return any(artifact_text.endswith(f"/{declared}") for declared in declared_files)


def _is_production_implementation_file(path: str) -> bool:
    """Return true for code/docs files allowed to evolve post-freeze."""

    return path.startswith(("src/", "tests/")) or path in {
        "app.py",
        "README.md",
        "CHANGELOG.md",
    }


def case_retrieval_ranks(report: Any, case_ids: list[str]) -> dict[str, int]:
    """Return retrieval rank by case id."""

    rank_by_case = {case.case_id: idx for idx, case in enumerate(report.retrieved_cases, start=1)}
    return {case_id: rank_by_case.get(case_id, 0) for case_id in case_ids}


def load_csv(path: str | Path) -> list[dict[str, str]]:
    """Load CSV rows."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [{key: (value or "") for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    """Write CSV rows."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["empty"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return output


def load_json(path: str | Path) -> dict[str, Any]:
    """Load JSON object."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write stable JSON."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 digest."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rate(numerator: int, denominator: int) -> float | None:
    """Return rounded rate or None."""

    if denominator == 0:
        return None
    return round(numerator / denominator, 6)
