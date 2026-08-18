"""Derived compatible-node funnel analysis for frozen temporal Attempt 002.

This module reads frozen held-out artifacts only. It does not rerun retrieval,
pipeline prediction, price fetching, returns, or CAR.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.mechanism_context import COMPATIBLE, INSUFFICIENT_CONTEXT, mechanism_compatibility
from src.schemas import EventAnalysis
from src.transmission_context_store import (
    load_historical_contexts,
    missing_context,
    project_current_event_context,
)
from src.validation.v4_temporal_prediction import assert_prediction_checksums_valid


ATTEMPT_002_PREDICTION_DIR = Path("data/validation_v4/predictions/attempt_002")
ATTEMPT_002_RESULTS_DIR = Path("data/validation_v4/results/attempt_002")
GROUND_TRUTH_PATH = Path("data/validation_v4/temporal_heldout_ground_truth.csv")
RAW_PREDICTIONS_PATH = ATTEMPT_002_PREDICTION_DIR / "v4_temporal_raw_predictions.json"
NODE_SNAPSHOT_PATH = ATTEMPT_002_PREDICTION_DIR / "v4_temporal_prediction_snapshot.csv"
PREDICTION_CHECKSUMS_PATH = ATTEMPT_002_PREDICTION_DIR / "v4_temporal_prediction_checksums.json"

FUNNEL_PATH = ATTEMPT_002_RESULTS_DIR / "v4_temporal_compatible_node_funnel.csv"
SUMMARY_PATH = ATTEMPT_002_RESULTS_DIR / "v4_temporal_compatible_node_funnel_summary.json"
POST_RETRIEVAL_LOSS_PATH = (
    ATTEMPT_002_RESULTS_DIR / "v4_temporal_post_retrieval_support_loss.csv"
)
NODE_DISCOVERY_MISS_PATH = (
    ATTEMPT_002_RESULTS_DIR / "v4_temporal_node_discovery_misses.csv"
)


def build_compatible_node_funnel(
    ground_truth_path: str | Path = GROUND_TRUTH_PATH,
    raw_predictions_path: str | Path = RAW_PREDICTIONS_PATH,
    node_snapshot_path: str | Path = NODE_SNAPSHOT_PATH,
    prediction_checksums_path: str | Path = PREDICTION_CHECKSUMS_PATH,
    output_path: str | Path = FUNNEL_PATH,
    summary_path: str | Path = SUMMARY_PATH,
    post_retrieval_loss_path: str | Path = POST_RETRIEVAL_LOSS_PATH,
    node_discovery_miss_path: str | Path = NODE_DISCOVERY_MISS_PATH,
) -> dict[str, Any]:
    """Build the post-freeze funnel for compatible ground-truth nodes only."""

    assert_prediction_checksums_valid(prediction_checksums_path)
    ground_truth = [
        row
        for row in load_csv(ground_truth_path)
        if row["expected_support_class"] == "compatible_support_expected"
    ]
    if len(ground_truth) != 21:
        raise RuntimeError(f"compatible_funnel_population_mismatch:{len(ground_truth)}")

    raw_by_event = {
        row["event_id"]: row
        for row in load_json(raw_predictions_path).get("predictions", [])
    }
    node_snapshot = load_csv(node_snapshot_path)
    final_nodes = {
        (row["event_id"], row["node"]): row
        for row in node_snapshot
        if row.get("predicted_support_status", "").startswith("accepted")
    }
    historical_contexts = load_historical_contexts()

    funnel_rows = [
        analyze_pair(truth, raw_by_event[truth["event_id"]], final_nodes, historical_contexts)
        for truth in ground_truth
    ]
    write_csv(output_path, funnel_rows)
    write_csv(
        post_retrieval_loss_path,
        [row for row in funnel_rows if row["legacy_style_raw_support_pass"] and not row["threshold_pass"]],
    )
    write_csv(
        node_discovery_miss_path,
        [
            row
            for row in funnel_rows
            if not row["current_node_proposed"]
            and (
                row["raw_same_node_support_count"] >= 1
                or row["mechanism_relevant_evidence_in_top10"]
            )
        ],
    )
    summary = summarize_funnel(funnel_rows)
    write_json(summary_path, summary)
    return summary


def analyze_pair(
    truth: dict[str, str],
    raw_prediction: dict[str, Any],
    final_nodes: dict[tuple[str, str], dict[str, str]],
    historical_contexts: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    """Analyze one compatible expected event/node pair through the frozen funnel."""

    event_id = truth["event_id"]
    expected_node = truth["node"]
    report = raw_prediction.get("report", {})
    event = EventAnalysis(**report["event"])
    retrieved_cases = report.get("retrieved_cases", [])
    event_nodes = set(report.get("event", {}).get("supply_chain_nodes", []))
    affected_nodes = set(report.get("transmission_chain", {}).get("affected_nodes", []))
    current_node_proposed = expected_node in event_nodes or expected_node in affected_nodes
    node_proposal_source = proposal_source(expected_node, event_nodes, affected_nodes)

    raw_same_cases = [
        (idx, case)
        for idx, case in enumerate(retrieved_cases, start=1)
        if expected_node in case.get("supply_chain_nodes", [])
    ]
    raw_same_case_ids = [case["case_id"] for _, case in raw_same_cases]
    raw_same_ranks = {case["case_id"]: idx for idx, case in raw_same_cases}

    current_context = project_current_event_context(event, expected_node)
    current_context_available = current_context is not None
    current_context_complete = is_informative_context(current_context)
    context_not_attempted = not current_node_proposed

    supporting_contexts = []
    historical_missing = []
    for rank, case in raw_same_cases:
        case_id = case["case_id"]
        context = historical_contexts.get((case_id, expected_node))
        if context and is_informative_context(context):
            supporting_contexts.append((rank, case_id, context))
        else:
            historical_missing.append(case_id)

    compatibility_rows = []
    counts = Counter()
    for rank, case_id, context in supporting_contexts:
        decision = mechanism_compatibility(current_context, context)
        compatibility_rows.append(
            {
                "historical_case_id": case_id,
                "retrieval_rank": rank,
                "raw_same_node_match": True,
                "historical_context_available": True,
                "current_context_available": current_context_available,
                "compatibility_result": decision.status,
                "compatibility_match_type": decision.match_type,
            }
        )
        counts[decision.status] += 1
        if decision.status == COMPATIBLE:
            counts[f"match_{decision.match_type}"] += 1

    mechanism_relevant, mechanism_notes = mechanism_relevant_in_top10(
        expected_node=expected_node,
        current_context=current_context,
        retrieved_cases=retrieved_cases,
        historical_contexts=historical_contexts,
        raw_same_count=len(raw_same_cases),
    )

    compatible_count = counts[COMPATIBLE]
    exact_count = counts["match_exact"]
    family_count = counts["match_canonical_family"]
    incompatible_count = counts["incompatible"]
    insufficient_count = counts[INSUFFICIENT_CONTEXT]
    threshold_pass = compatible_count >= 2
    final_retained = (event_id, expected_node) in final_nodes
    first_stage, primary, secondary = classify_failure(
        current_node_proposed=current_node_proposed,
        raw_same_count=len(raw_same_cases),
        mechanism_relevant=mechanism_relevant,
        historical_context_count=len(supporting_contexts),
        current_context_available=current_context_available,
        compatible_count=compatible_count,
        insufficient_count=insufficient_count,
        threshold_pass=threshold_pass,
        final_retained=final_retained,
    )

    return {
        "event_id": event_id,
        "expected_node": expected_node,
        "current_node_proposed": current_node_proposed,
        "node_proposal_source": node_proposal_source,
        "stage_observable": True,
        "raw_same_node_support_count": len(raw_same_cases),
        "raw_same_node_support_ge1": len(raw_same_cases) >= 1,
        "raw_same_node_support_ge2": len(raw_same_cases) >= 2,
        "raw_same_node_case_ids": json.dumps(raw_same_case_ids, sort_keys=True),
        "raw_same_node_retrieval_ranks": json.dumps(raw_same_ranks, sort_keys=True),
        "mechanism_relevant_evidence_in_top10": mechanism_relevant,
        "mechanism_relevant_rationale": mechanism_notes,
        "historical_context_available_count": len(supporting_contexts),
        "historical_context_missing_count": len(historical_missing),
        "historical_context_ge1": len(supporting_contexts) >= 1,
        "historical_context_ge2": len(supporting_contexts) >= 2,
        "historical_context_missing_case_ids": json.dumps(historical_missing, sort_keys=True),
        "current_context_available": current_context_available,
        "current_context_complete": current_context_complete,
        "current_context_not_attempted_due_to_missing_node": context_not_attempted,
        "compatibility_case_diagnostics": json.dumps(compatibility_rows, sort_keys=True),
        "compatible_support_count": compatible_count,
        "exact_support_count": exact_count,
        "canonical_family_support_count": family_count,
        "incompatible_support_count": incompatible_count,
        "insufficient_support_count": insufficient_count,
        "threshold_pass": threshold_pass,
        "just_below_threshold": compatible_count == 1,
        "compatible_support_bucket": "2+" if compatible_count >= 2 else str(compatible_count),
        "final_node_retained": final_retained,
        "post_qualification_drop": threshold_pass and not final_retained,
        "legacy_style_raw_support_pass": len(raw_same_cases) >= 2,
        "first_failure_stage": first_stage,
        "primary_root_cause": primary,
        "secondary_root_cause": secondary,
        "loss_reason": loss_reason(
            current_node_proposed=current_node_proposed,
            raw_same_count=len(raw_same_cases),
            mechanism_relevant=mechanism_relevant,
            historical_context_count=len(supporting_contexts),
            current_context_available=current_context_available,
            compatible_count=compatible_count,
            threshold_pass=threshold_pass,
            final_retained=final_retained,
        ),
        "notes": mechanism_notes,
    }


def mechanism_relevant_in_top10(
    expected_node: str,
    current_context: dict[str, str] | None,
    retrieved_cases: list[dict[str, Any]],
    historical_contexts: dict[tuple[str, str], dict[str, str]],
    raw_same_count: int,
) -> tuple[bool, str]:
    """Detect frozen-rule mechanism relevance in top-10 without reretrieval."""

    if raw_same_count:
        return True, "top10 contains raw same-node historical evidence"
    if not current_context or not is_informative_context(current_context):
        return False, "current context unavailable, no raw same-node evidence"

    compatible_contexts = []
    for rank, case in enumerate(retrieved_cases, start=1):
        case_id = case["case_id"]
        for node in case.get("supply_chain_nodes", []):
            context = historical_contexts.get((case_id, node))
            if not context or not is_informative_context(context):
                continue
            decision = mechanism_compatibility(current_context, context)
            if decision.status == COMPATIBLE:
                compatible_contexts.append(f"{case_id}:{node}@{rank}:{decision.match_type}")
    if compatible_contexts:
        return True, "compatible non-exact node contexts in top10: " + ";".join(compatible_contexts)
    return False, "no raw same-node or frozen-compatible context evidence in top10"


def classify_failure(
    current_node_proposed: bool,
    raw_same_count: int,
    mechanism_relevant: bool,
    historical_context_count: int,
    current_context_available: bool,
    compatible_count: int,
    insufficient_count: int,
    threshold_pass: bool,
    final_retained: bool,
) -> tuple[str, str, str]:
    """Return first failure stage and root-cause labels."""

    if final_retained:
        return "PASS_final_retained", "pass_final_retained", ""
    if not current_node_proposed:
        secondary = "retrieved_evidence_present" if raw_same_count or mechanism_relevant else "retrieval_or_vocabulary_gap"
        return "A_node_not_proposed", "node_generation_gap", secondary
    if raw_same_count == 0:
        return "B_no_same_node_evidence_top10", "retrieval_gap", ""
    if historical_context_count == 0:
        return "C_historical_context_missing", "historical_representation_gap", ""
    if not current_context_available:
        return "D_current_context_missing", "current_projection_gap", ""
    if insufficient_count and compatible_count == 0:
        return "E_mechanism_insufficient", "historical_representation_gap", "current_projection_gap"
    if compatible_count == 0:
        return "E_mechanism_incompatible", "mechanism_mismatch", ""
    if not threshold_pass:
        return "F_support_count_below_threshold", "support_threshold_effect", ""
    return "G_post_qualification_drop", "post_qualification_bug", ""


def loss_reason(
    current_node_proposed: bool,
    raw_same_count: int,
    mechanism_relevant: bool,
    historical_context_count: int,
    current_context_available: bool,
    compatible_count: int,
    threshold_pass: bool,
    final_retained: bool,
) -> str:
    """Return a compact loss explanation for diagnostic subsets."""

    if final_retained:
        return "final_retained"
    if not current_node_proposed and (raw_same_count or mechanism_relevant):
        return "retrieved_evidence_present_but_current_node_not_proposed"
    if not current_node_proposed:
        return "current_node_not_proposed_and_no_frozen_top10_evidence"
    if raw_same_count == 0:
        return "no_raw_same_node_evidence_top10"
    if historical_context_count == 0:
        return "historical_context_missing_for_raw_same_node_cases"
    if not current_context_available:
        return "current_context_missing"
    if compatible_count == 0:
        return "mechanism_not_compatible_under_frozen_rule"
    if not threshold_pass:
        return "compatible_support_count_below_threshold"
    return "post_qualification_drop"


def summarize_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize compatible-node funnel rows."""

    total = len(rows)
    stages = Counter(row["first_failure_stage"] for row in rows)
    roots = Counter(row["primary_root_cause"] for row in rows)
    false_miss_roots = Counter(
        row["primary_root_cause"] for row in rows if not row["final_node_retained"]
    )
    false_miss_secondary = Counter(
        row["secondary_root_cause"]
        for row in rows
        if not row["final_node_retained"] and row["secondary_root_cause"]
    )
    post_retrieval_losses = [
        row for row in rows if row["legacy_style_raw_support_pass"] and not row["threshold_pass"]
    ]
    node_discovery_misses = [
        row
        for row in rows
        if not row["current_node_proposed"]
        and (
            row["raw_same_node_support_count"] >= 1
            or row["mechanism_relevant_evidence_in_top10"]
        )
    ]
    return {
        "diagnostic_counterfactual_only": True,
        "compatible_ground_truth_total": total,
        "current_node_proposed": count(rows, "current_node_proposed"),
        "raw_same_node_evidence_ge1_top10": count(rows, "raw_same_node_support_ge1"),
        "raw_same_node_evidence_ge2_top10": count(rows, "raw_same_node_support_ge2"),
        "no_raw_same_node_evidence_top10": sum(
            row["raw_same_node_support_count"] == 0 for row in rows
        ),
        "mechanism_relevant_historical_evidence_top10": count(
            rows, "mechanism_relevant_evidence_in_top10"
        ),
        "historical_context_ge2_available": count(rows, "historical_context_ge2"),
        "current_context_available": count(rows, "current_context_available"),
        "compatible_support_ge1": sum(row["compatible_support_count"] >= 1 for row in rows),
        "compatible_support_ge2": sum(row["compatible_support_count"] >= 2 for row in rows),
        "final_retained": count(rows, "final_node_retained"),
        "legacy_style_raw_support_pass": count(rows, "legacy_style_raw_support_pass"),
        "v4_compatible_support_pass": sum(row["compatible_support_count"] >= 2 for row in rows),
        "post_retrieval_support_loss_count": len(post_retrieval_losses),
        "retrieved_evidence_present_but_node_not_proposed": len(node_discovery_misses),
        "first_failure_stage_counts": dict(stages),
        "primary_root_cause_counts": dict(roots),
        "original_18_miss_reclassified_root_causes": dict(false_miss_roots),
        "original_18_miss_secondary_root_causes": dict(false_miss_secondary),
        "prices_accessed": False,
        "returns_accessed": False,
        "CAR_run": False,
    }


def proposal_source(node: str, event_nodes: set[str], affected_nodes: set[str]) -> str:
    """Identify where a node is observable in the frozen raw report."""

    if node in event_nodes:
        return "event_analyst"
    if node in affected_nodes:
        return "transmission_builder"
    return "not_proposed"


def is_informative_context(context: dict[str, Any] | None) -> bool:
    """Return True only when all required context fields are informative."""

    if not context:
        return False
    return all(context.get(field) not in {"", "unknown", "unavailable", None} for field in [
        "shock_type",
        "constraint_type",
        "upstream_driver",
        "target_node_role",
        "canonical_context",
    ])


def count(rows: list[dict[str, Any]], key: str) -> int:
    """Count truthy values for a row key."""

    return sum(bool(row[key]) for row in rows)


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
    """Load a JSON object."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write stable JSON."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
