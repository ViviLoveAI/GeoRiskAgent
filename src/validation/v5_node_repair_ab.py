"""Scoped V4 vs V5 node-repair A/B evaluation.

This module writes V5-only derived artifacts. It reads frozen V4 temporal
Attempt 002 artifacts as the baseline and runs V5 on the same sealed events.
It does not modify V4 artifacts, checksums, benchmark definitions, or evidence
methodology.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from src.validation.v4_compatible_node_funnel import (
    analyze_pair,
    classify_failure,
    loss_reason,
    summarize_funnel,
)
from src.validation.v4_temporal_prediction import (
    asset_snapshot_rows,
    evaluate_class,
    load_csv,
    mechanism_summary,
    node_snapshot_rows,
    predicted_class_for,
    raw_prediction_record,
)
from src.v4_config import V4_CONFIG, assert_v4_config
from src.v5_config import V5_CONFIG, V5DiscoveryConfig, assert_v5_config
from src.v5_pipeline import run_v5_pipeline


V4_ATTEMPT_002_DIR = Path("data/validation_v4/predictions/attempt_002")
V4_ATTEMPT_002_RESULTS_DIR = Path("data/validation_v4/results/attempt_002")
TEMPORAL_EVENTS_PATH = Path("data/validation_v4/temporal_final_heldout_events.csv")
GROUND_TRUTH_PATH = Path("data/validation_v4/temporal_heldout_ground_truth.csv")
V4_RAW_PREDICTIONS_PATH = V4_ATTEMPT_002_DIR / "v4_temporal_raw_predictions.json"
V4_NODE_SNAPSHOT_PATH = V4_ATTEMPT_002_DIR / "v4_temporal_prediction_snapshot.csv"
V4_MECHANISM_SUMMARY_PATH = (
    V4_ATTEMPT_002_RESULTS_DIR / "v4_temporal_mechanism_evaluation_summary.json"
)
V4_FUNNEL_PATH = V4_ATTEMPT_002_RESULTS_DIR / "v4_temporal_compatible_node_funnel.csv"
V4_FUNNEL_SUMMARY_PATH = (
    V4_ATTEMPT_002_RESULTS_DIR / "v4_temporal_compatible_node_funnel_summary.json"
)

DEFAULT_OUTPUT_DIR = Path("data/validation_v5/node_repair_ab")
SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_ab_summary.json"
FUNNEL_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_funnel.csv"
EVENT_RESULTS_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_event_results.csv"
TRAJECTORY_REVIEW_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_trajectory_review.csv"
MECHANISM_EVALUATION_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_mechanism_evaluation.csv"
RAW_PREDICTIONS_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_raw_predictions.json"
NODE_SNAPSHOT_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_node_snapshot.csv"
ASSET_SNAPSHOT_PATH = DEFAULT_OUTPUT_DIR / "v5_node_repair_asset_snapshot.csv"
TRAJECTORY_REVIEW_FIELDS = [
    "event_id",
    "diagnosis",
    "added_candidate_node",
    "historical_evidence_present",
    "current_proposal_present",
    "source_case_ids",
    "historical_support_count",
    "current_context_available",
    "projection_attempted",
    "projection_source",
    "projection_status",
    "projection_cues",
    "applicability_status",
    "applicability_reason",
    "compatible_support_count_at_proposal",
    "specificity_recovery_evaluated",
    "specificity_recovery_eligible",
    "specificity_recovery_reason",
    "candidate_source",
    "candidate_specificity",
    "event_default_broad",
    "event_guardrail_bypassed_for_candidate",
    "downstream_final_status",
    "downstream_final_reason",
    "support_delta",
    "verification_result",
    "final_status",
]
ACCEPTED_REVIEW_PATH = DEFAULT_OUTPUT_DIR / "v5_specificity_recovery_accepted_review.csv"
ACCEPTED_REVIEW_FIELDS = [
    "event_id",
    "node",
    "gt_compatible",
    "source_case_ids",
    "projected_current_context",
    "projection_cues",
    "current_event_applicability_status",
    "current_event_applicability_reason",
    "compatible_support",
    "specificity_recovery_reason",
    "mapped_assets",
    "evidence_grades",
    "final_status",
]


def run_v5_node_repair_ab(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    config: V5DiscoveryConfig = V5_CONFIG,
) -> dict[str, Any]:
    """Run the scoped temporal held-out V4 vs V5 node-repair evaluation."""

    assert_v4_config(V4_CONFIG)
    assert_v5_config(config)
    output = Path(output_dir)
    paths = _paths(output)

    events = load_csv(TEMPORAL_EVENTS_PATH)
    ground_truth = load_csv(GROUND_TRUTH_PATH)
    raw_predictions: list[dict[str, Any]] = []
    node_rows: list[dict[str, Any]] = []
    asset_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    trajectory_rows: list[dict[str, Any]] = []
    accepted_review_rows: list[dict[str, Any]] = []
    success_count = 0
    runtime_failure_count = 0
    compatible_gt = {
        (row["event_id"], row["node"])
        for row in ground_truth
        if row["expected_support_class"] == "compatible_support_expected"
    }

    for event in events:
        event_id = event["event_id"]
        try:
            result = run_v5_pipeline(
                event["short_description"],
                event_analyzer="rule",
                config=config,
            )
            report = result.final_report
            projection_overrides = {
                node: projection.projected_current_context
                for node, projection in result.state.current_context_projections.items()
                if projection.projected_current_context is not None
            }
            raw_predictions.append(
                {
                    **raw_prediction_record(event, report, status="success"),
                    "v5_metadata": {
                        "architecture_version": result.architecture_version,
                        "repair_policy_version": result.repair_policy_version,
                        "repair_enabled": result.repair_enabled,
                        "specificity_recovery_enabled": config.enable_specificity_recovery,
                        "current_event_applicability_gate_enabled": (
                            config.enable_current_event_applicability_gate
                        ),
                        "diagnosis": result.state.diagnosis,
                        "repair_attempts": result.state.repair_attempts,
                        "historical_evidence_nodes": result.state.historical_evidence_nodes,
                        "current_proposed_nodes": result.state.current_proposed_nodes,
                        "repair_candidate_pool": result.state.repair_candidate_pool,
                        "repaired_candidate_nodes": result.state.repaired_candidate_nodes,
                        "current_context_projections": {
                            node: projection.model_dump(mode="json")
                            for node, projection in result.state.current_context_projections.items()
                        },
                        "repair_proposals": [
                            proposal.model_dump(mode="json")
                            for proposal in result.state.repair_proposals
                        ],
                        "trajectory": [
                            action.model_dump(mode="json")
                            for action in result.state.trajectory
                        ],
                    },
                }
            )
            with _prediction_projection_overrides(projection_overrides):
                node_rows.extend(node_snapshot_rows(event_id, report))
            asset_rows.extend(asset_snapshot_rows(event_id, report))
            event_rows.append(event_result_row(event_id, result))
            trajectory_rows.extend(trajectory_review_rows(event_id, result))
            accepted_review_rows.extend(
                accepted_repaired_review_rows(event_id, result, compatible_gt)
            )
            success_count += 1
        except Exception as exc:  # pragma: no cover - retained for auditability.
            raw_predictions.append(
                {
                    "event_id": event_id,
                    "status": "runtime_failure",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "input_event": event,
                }
            )
            event_rows.append(
                {
                    "event_id": event_id,
                    "status": "runtime_failure",
                    "diagnosis": "",
                    "repair_attempts": 0,
                    "candidates_added_count": 0,
                    "candidate_nodes_added": "[]",
                    "final_retained_added_nodes": "[]",
                    "latency_ms": 0,
                    "retrieval_rounds": 0,
                    "additional_llm_calls": 0,
                "token_usage_available": False,
            }
        )
            runtime_failure_count += 1

    write_json(
        paths["raw_predictions"],
        {
            "attempt_id": "v5_node_repair_ab",
            "benchmark_version": "v4_temporal_heldout_v1",
            "condition": "v5_node_repair",
            "ground_truth_accessed_during_generation": False,
            "prices_accessed": False,
            "returns_accessed": False,
            "CAR_run": False,
            "predictions": raw_predictions,
        },
    )
    write_csv(paths["node_snapshot"], node_rows)
    write_csv(paths["asset_snapshot"], asset_rows)
    write_csv(paths["event_results"], event_rows)
    write_csv(paths["trajectory_review"], trajectory_rows, fields=TRAJECTORY_REVIEW_FIELDS)
    write_csv(paths["accepted_review"], accepted_review_rows, fields=ACCEPTED_REVIEW_FIELDS)

    evaluation_rows = evaluate_mechanisms(ground_truth, node_rows)
    write_csv(paths["mechanism_evaluation"], evaluation_rows)
    v5_mechanism_summary = mechanism_summary(evaluation_rows)

    v5_funnel_rows = build_v5_funnel(ground_truth, raw_predictions, node_rows)
    write_csv(paths["funnel"], v5_funnel_rows)
    v5_funnel_summary = summarize_funnel(v5_funnel_rows)

    v4_funnel_rows = read_csv(V4_FUNNEL_PATH)
    v4_funnel_summary = load_json(V4_FUNNEL_SUMMARY_PATH)
    v4_mechanism_summary = load_json(V4_MECHANISM_SUMMARY_PATH)
    repair_summary = summarize_repairs(event_rows, trajectory_rows, ground_truth, v5_funnel_rows)
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark_version": "v4_temporal_heldout_v1",
        "conditions": {
            "v4_baseline": "frozen_attempt_002",
            "v5_node_repair": config.architecture_version,
        },
        "selected_event_count": len(events),
        "success_count": success_count,
        "runtime_failure_count": runtime_failure_count,
        "v4_config": {
            "top_k": V4_CONFIG.retrieval_top_k,
            "mechanism_compatible_support": V4_CONFIG.use_mechanism_compatible_support,
            "support_threshold": V4_CONFIG.compatible_support_threshold,
        },
        "v5_config": {
            "architecture_version": config.architecture_version,
            "repair_policy_version": config.repair_policy_version,
            "enable_node_repair": config.enable_node_repair,
            "enable_specificity_recovery": config.enable_specificity_recovery,
            "enable_current_event_applicability_gate": (
                config.enable_current_event_applicability_gate
            ),
            "max_repair_attempts": config.max_repair_attempts,
            "max_new_candidate_nodes": config.max_new_candidate_nodes,
        },
        "funnel_comparison": funnel_comparison(v4_funnel_summary, v5_funnel_summary),
        "mechanism_quality_comparison": quality_comparison(
            v4_mechanism_summary,
            v5_mechanism_summary,
        ),
        "failure_migration": failure_migration(v4_funnel_rows, v5_funnel_rows),
        "repair_summary": repair_summary,
        "specificity_recovery_summary": summarize_specificity_recovery(
            trajectory_rows,
            accepted_review_rows,
            ground_truth,
        ),
        "cost_engineering": cost_engineering(event_rows),
        "artifact_paths": {name: str(path) for name, path in paths.items()},
        "prices_accessed": False,
        "returns_accessed": False,
        "CAR_run": False,
    }
    write_json(paths["summary"], summary)
    return summary


def evaluate_mechanisms(
    ground_truth: list[dict[str, str]],
    node_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate V5 node rows using the frozen V4 evaluation classes."""

    predicted_by_key = {(row["event_id"], row["node"]): row for row in node_rows}
    evaluation_rows = []
    for truth in ground_truth:
        prediction = predicted_by_key.get((truth["event_id"], truth["node"]))
        predicted_class = predicted_class_for(prediction)
        correct, error_type = evaluate_class(
            truth["expected_support_class"],
            predicted_class,
        )
        evaluation_rows.append(
            {
                "event_id": truth["event_id"],
                "node": truth["node"],
                "ground_truth_class": truth["expected_support_class"],
                "predicted_class": predicted_class,
                "correct": correct,
                "error_type": error_type,
                "representation_gap_observed": truth.get("representation_gap_observed", "False"),
                "notes": truth.get("review_notes", ""),
            }
        )
    return evaluation_rows


def build_v5_funnel(
    ground_truth: list[dict[str, str]],
    raw_predictions: list[dict[str, Any]],
    node_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a V5-compatible node funnel using the existing V4 analyzer."""

    compatible_truth = [
        row for row in ground_truth
        if row["expected_support_class"] == "compatible_support_expected"
    ]
    raw_by_event = {row["event_id"]: row for row in raw_predictions}
    final_nodes = {
        (row["event_id"], row["node"]): row
        for row in node_rows
        if str(row.get("predicted_support_status", "")).startswith("accepted")
    }
    from src.transmission_context_store import load_historical_contexts

    historical_contexts = load_historical_contexts()
    rows = [
        analyze_pair(truth, raw_by_event[truth["event_id"]], final_nodes, historical_contexts)
        for truth in compatible_truth
    ]
    repair_by_event = repair_lookup(raw_predictions)
    for row in rows:
        repair = repair_by_event.get(row["event_id"], {})
        added_nodes = set(repair.get("added_nodes", []))
        proposal = repair.get("proposals", {}).get(row["expected_node"], {})
        row["v5_repair_triggered"] = bool(repair.get("repair_attempts", 0))
        row["v5_repair_added_expected_node"] = row["expected_node"] in added_nodes
        row["v5_added_candidate_nodes"] = json.dumps(sorted(added_nodes))
        row["specificity_recovery_eligible"] = bool(
            proposal.get("specificity_recovery_eligible", False)
        )
        row["entered_downstream_qualification"] = bool(
            proposal.get("event_guardrail_bypassed_for_candidate", False)
        )
        if row["v5_repair_added_expected_node"]:
            projection = repair.get("projections", {}).get(row["expected_node"], {})
            if projection.get("projected_current_context"):
                row["current_context_available"] = True
                row["current_context_complete"] = True
            if proposal:
                row["compatible_support_count"] = int(proposal.get("compatible_support_count", 0))
                row["threshold_pass"] = int(row["compatible_support_count"]) >= 2
                row["compatible_support_bucket"] = (
                    "2+" if int(row["compatible_support_count"]) >= 2 else str(row["compatible_support_count"])
                )
            row["current_node_proposed"] = True
            row["node_proposal_source"] = "node_repair"
            row["current_context_not_attempted_due_to_missing_node"] = False
        if row["v5_repair_added_expected_node"] and not row["final_node_retained"]:
            first_stage, primary, secondary = classify_failure(
                current_node_proposed=True,
                raw_same_count=int(row["raw_same_node_support_count"]),
                mechanism_relevant=as_bool(row["mechanism_relevant_evidence_in_top10"]),
                historical_context_count=int(row["historical_context_available_count"]),
                current_context_available=as_bool(row["current_context_available"]),
                compatible_count=int(row["compatible_support_count"]),
                insufficient_count=int(row["insufficient_support_count"]),
                threshold_pass=as_bool(row["threshold_pass"]),
                final_retained=as_bool(row["final_node_retained"]),
            )
            row["first_failure_stage"] = first_stage
            row["primary_root_cause"] = primary
            row["secondary_root_cause"] = secondary
            row["loss_reason"] = loss_reason(
                current_node_proposed=True,
                raw_same_count=int(row["raw_same_node_support_count"]),
                mechanism_relevant=as_bool(row["mechanism_relevant_evidence_in_top10"]),
                historical_context_count=int(row["historical_context_available_count"]),
                current_context_available=as_bool(row["current_context_available"]),
                compatible_count=int(row["compatible_support_count"]),
                threshold_pass=as_bool(row["threshold_pass"]),
                final_retained=as_bool(row["final_node_retained"]),
            )
            if as_bool(row["threshold_pass"]) and not as_bool(row["final_node_retained"]):
                row["first_failure_stage"] = "H_broad_node_guardrail"
                row["primary_root_cause"] = "broad_node_guardrail"
                row["secondary_root_cause"] = "default_limited_support_event"
                row["loss_reason"] = "compatible_support_passed_but_broad_node_guardrail_blocked_final_retention"
    return rows


def event_result_row(event_id: str, result: Any) -> dict[str, Any]:
    """Summarize one V5 event run."""

    added = [proposal.proposed_node for proposal in result.state.repair_proposals]
    retained = [
        node for node in added
        if node in result.final_report.transmission_chain.affected_nodes
    ]
    return {
        "event_id": event_id,
        "status": "success",
        "diagnosis": result.state.diagnosis or "",
        "repair_attempts": result.state.repair_attempts,
        "candidates_added_count": len(added),
        "candidate_nodes_added": json.dumps(added, sort_keys=True),
        "final_retained_added_nodes": json.dumps(retained, sort_keys=True),
        "latency_ms": sum(action.latency_ms for action in result.state.trajectory),
        "retrieval_rounds": result.state.retrieval_attempts,
        "additional_llm_calls": 0,
        "token_usage_available": False,
    }


def trajectory_review_rows(event_id: str, result: Any) -> list[dict[str, Any]]:
    """Return compact human-readable repair trajectory rows."""

    if not result.state.repair_proposals:
        return []
    retained = set(result.final_report.transmission_chain.affected_nodes)
    support_delta: dict[str, int] = {}
    for action in result.state.trajectory:
        support_delta.update(action.support_delta)
    rows = []
    for proposal in result.state.repair_proposals:
        final_status = (
            "final_retained"
            if proposal.proposed_node in retained
            else "rejected_by_frozen_v4_verify"
        )
        rows.append(
            {
                "event_id": event_id,
                "diagnosis": result.state.diagnosis or "",
                "added_candidate_node": proposal.proposed_node,
                "historical_evidence_present": proposal.proposed_node
                in result.state.historical_evidence_nodes,
                "current_proposal_present": proposal.proposed_node
                not in result.state.repair_candidate_pool,
                "source_case_ids": json.dumps(proposal.source_case_ids, sort_keys=True),
                "historical_support_count": proposal.historical_support_count,
                "current_context_available": proposal.current_context_available,
                "projection_attempted": proposal.projection_attempted,
                "projection_source": proposal.projection_source or "",
                "projection_status": proposal.projection_status,
                "projection_cues": json.dumps(proposal.projection_cues, sort_keys=True),
                "applicability_status": proposal.applicability_status,
                "applicability_reason": proposal.applicability_reason,
                "compatible_support_count_at_proposal": proposal.compatible_support_count,
                "specificity_recovery_evaluated": proposal.specificity_recovery_evaluated,
                "specificity_recovery_eligible": proposal.specificity_recovery_eligible,
                "specificity_recovery_reason": proposal.specificity_recovery_reason,
                "candidate_source": proposal.candidate_source,
                "candidate_specificity": proposal.candidate_specificity,
                "event_default_broad": proposal.event_default_broad,
                "event_guardrail_bypassed_for_candidate": proposal.event_guardrail_bypassed_for_candidate,
                "downstream_final_status": proposal.downstream_final_status,
                "downstream_final_reason": proposal.downstream_final_reason,
                "support_delta": support_delta.get(proposal.proposed_node, 0),
                "verification_result": final_status,
                "final_status": final_status,
            }
        )
    return rows


def accepted_repaired_review_rows(
    event_id: str,
    result: Any,
    compatible_gt: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Return audit rows for repaired candidates accepted in final output."""

    retained = set(result.final_report.transmission_chain.affected_nodes)
    rows = []
    for proposal in result.state.repair_proposals:
        node = proposal.proposed_node
        if node not in retained:
            continue
        evidence = [
            item
            for item in result.final_report.evidence_results
            if item.asset.supply_chain_node == node
        ]
        rows.append(
            {
                "event_id": event_id,
                "node": node,
                "gt_compatible": (event_id, node) in compatible_gt,
                "source_case_ids": json.dumps(proposal.source_case_ids, sort_keys=True),
                "projected_current_context": json.dumps(
                    proposal.projected_current_context or {},
                    sort_keys=True,
                ),
                "projection_cues": json.dumps(proposal.projection_cues, sort_keys=True),
                "current_event_applicability_status": proposal.applicability_status,
                "current_event_applicability_reason": proposal.applicability_reason,
                "compatible_support": proposal.compatible_support_count,
                "specificity_recovery_reason": proposal.specificity_recovery_reason,
                "mapped_assets": json.dumps(
                    [
                        {
                            "ticker": item.ticker,
                            "asset_name": item.asset_name,
                            "linkage_tier": item.linkage_tier,
                        }
                        for item in evidence
                    ],
                    sort_keys=True,
                ),
                "evidence_grades": json.dumps(
                    sorted({item.evidence_grade for item in evidence}),
                    sort_keys=True,
                ),
                "final_status": "final_retained",
            }
        )
    return rows


def summarize_repairs(
    event_rows: list[dict[str, Any]],
    trajectory_rows: list[dict[str, Any]],
    ground_truth: list[dict[str, str]],
    v5_funnel_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize V5 repair-specific metrics."""

    successful_events = [row for row in event_rows if row["status"] == "success"]
    repaired_events = [row for row in successful_events if int(row["repair_attempts"]) > 0]
    added_counts = [int(row["candidates_added_count"]) for row in repaired_events]
    compatible_gt = {
        (row["event_id"], row["node"])
        for row in ground_truth
        if row["expected_support_class"] == "compatible_support_expected"
    }
    recovered_gt = [
        row for row in v5_funnel_rows
        if row.get("v5_repair_added_expected_node") and (row["event_id"], row["expected_node"]) in compatible_gt
    ]
    retained_repaired = [
        row for row in trajectory_rows if row["final_status"] == "final_retained"
    ]
    rejected_repaired = [
        row for row in trajectory_rows if row["final_status"] != "final_retained"
    ]
    useful_events = {
        row["event_id"]
        for row in retained_repaired
        if (row["event_id"], row["added_candidate_node"]) in compatible_gt
    }
    neutral_events = {
        row["event_id"]
        for row in trajectory_rows
        if row["event_id"] not in useful_events
    }
    return {
        "repair_invocation_rate": rate(len(repaired_events), len(successful_events)),
        "events_repaired": len(repaired_events),
        "repair_success_rate": rate(len(useful_events), len(repaired_events)),
        "total_candidates_added": sum(added_counts),
        "mean_candidates_added_per_repair": round(mean(added_counts), 6) if added_counts else 0,
        "max_candidates_added": max(added_counts) if added_counts else 0,
        "gt_compatible_candidates_recovered": len(recovered_gt),
        "repaired_candidates_passing_mechanism_compatibility": sum(
            int(row["compatible_support_count_at_proposal"]) >= 1
            for row in trajectory_rows
        ),
        "repaired_candidates_passing_support_ge2": sum(
            int(row["compatible_support_count_at_proposal"]) >= 2
            for row in trajectory_rows
        ),
        "repaired_candidates_finally_retained": len(retained_repaired),
        "projection_attempted": sum(
            str(row.get("projection_attempted")) == "True"
            for row in trajectory_rows
        ),
        "projection_succeeded": sum(
            str(row.get("projection_status")) in {"projected", "existing_v4_context"}
            for row in trajectory_rows
        ),
        "gt_compatible_projection_attempted": sum(
            (row["event_id"], row["added_candidate_node"]) in compatible_gt
            and str(row.get("projection_attempted")) == "True"
            for row in trajectory_rows
        ),
        "gt_compatible_projection_succeeded": sum(
            (row["event_id"], row["added_candidate_node"]) in compatible_gt
            and str(row.get("projection_status")) in {"projected", "existing_v4_context"}
            for row in trajectory_rows
        ),
        "other_repair_projection_succeeded": sum(
            (row["event_id"], row["added_candidate_node"]) not in compatible_gt
            and str(row.get("projection_status")) in {"projected", "existing_v4_context"}
            for row in trajectory_rows
        ),
        "useful_repair_events": len(useful_events),
        "neutral_repair_events": len(neutral_events - useful_events),
        "rejected_repair_candidates": len(rejected_repaired),
    }


def summarize_specificity_recovery(
    trajectory_rows: list[dict[str, Any]],
    accepted_review_rows: list[dict[str, Any]],
    ground_truth: list[dict[str, str]],
) -> dict[str, Any]:
    """Summarize candidate-local specificity recovery behavior."""

    compatible_gt = {
        (row["event_id"], row["node"])
        for row in ground_truth
        if row["expected_support_class"] == "compatible_support_expected"
    }
    evaluated = [
        row for row in trajectory_rows
        if as_bool(row.get("specificity_recovery_evaluated"))
    ]
    eligible = [
        row for row in trajectory_rows
        if as_bool(row.get("specificity_recovery_eligible"))
    ]
    bypassed = [
        row for row in trajectory_rows
        if as_bool(row.get("event_guardrail_bypassed_for_candidate"))
    ]
    accepted_gt = [
        row for row in accepted_review_rows
        if as_bool(row.get("gt_compatible"))
    ]
    accepted_non_gt = [
        row for row in accepted_review_rows
        if not as_bool(row.get("gt_compatible"))
    ]
    return {
        "specificity_recovery_evaluated": len(evaluated),
        "specificity_recovery_eligible": len(eligible),
        "event_guardrail_bypassed_for_candidate": len(bypassed),
        "downstream_qualification_entered": len(bypassed),
        "accepted_repaired_candidates": len(accepted_review_rows),
        "accepted_gt_repaired_candidates": len(accepted_gt),
        "accepted_non_gt_repaired_candidates": len(accepted_non_gt),
        "eligible_gt_repaired_candidates": sum(
            (row["event_id"], row["added_candidate_node"]) in compatible_gt
            for row in eligible
        ),
        "eligible_non_gt_repaired_candidates": sum(
            (row["event_id"], row["added_candidate_node"]) not in compatible_gt
            for row in eligible
        ),
    }


def funnel_comparison(v4: dict[str, Any], v5: dict[str, Any]) -> list[dict[str, Any]]:
    """Return required V4/V5 funnel stage comparison."""

    stages = [
        ("compatible_ground_truth_nodes", "compatible_ground_truth_total"),
        ("current_candidate_node_proposed", "current_node_proposed"),
        ("raw_same_node_evidence_ge1", "raw_same_node_evidence_ge1_top10"),
        ("raw_same_node_evidence_ge2", "raw_same_node_evidence_ge2_top10"),
        ("current_context_available", "current_context_available"),
        ("mechanism_compatible_support_ge1", "compatible_support_ge1"),
        ("mechanism_compatible_support_ge2", "compatible_support_ge2"),
        ("final_retained", "final_retained"),
    ]
    return [
        {
            "stage": label,
            "v4_count": int(v4.get(key, 0)),
            "v5_count": int(v5.get(key, 0)),
            "delta": int(v5.get(key, 0)) - int(v4.get(key, 0)),
        }
        for label, key in stages
    ]


def quality_comparison(v4: dict[str, Any], v5: dict[str, Any]) -> dict[str, Any]:
    """Compare frozen evidence-quality metrics."""

    keys = [
        "compatible_retained",
        "compatible_retention_rate",
        "weak_rejected",
        "weak_rejection_rate",
        "weak_leakage",
        "weak_leakage_rate",
        "false_acceptance",
        "false_rejection",
        "correct_insufficient",
        "insufficient_handling_rate",
        "runtime_failure",
    ]
    result = {}
    for key in keys:
        result[key] = {
            "v4": v4.get(key),
            "v5": v5.get(key),
            "delta": _delta(v4.get(key), v5.get(key)),
        }
    return result


def failure_migration(
    v4_rows: list[dict[str, Any]],
    v5_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare failure-stage distributions for compatible GT nodes."""

    v4_stage = Counter(row["first_failure_stage"] for row in v4_rows)
    v5_stage = Counter(row["first_failure_stage"] for row in v5_rows)
    v4_root = Counter(row["primary_root_cause"] for row in v4_rows)
    v5_root = Counter(row["primary_root_cause"] for row in v5_rows)
    return {
        "first_failure_stage": compare_counters(v4_stage, v5_stage),
        "primary_root_cause": compare_counters(v4_root, v5_root),
        "node_generation_gap_delta": v5_root["node_generation_gap"] - v4_root["node_generation_gap"],
    }


def cost_engineering(event_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize available cost and engineering metrics."""

    successful = [row for row in event_rows if row["status"] == "success"]
    return {
        "mean_v5_latency_ms": round(mean([int(row["latency_ms"]) for row in successful]), 6)
        if successful
        else 0,
        "additional_llm_calls": sum(int(row["additional_llm_calls"]) for row in successful),
        "token_delta_available": False,
        "retrieval_rounds_total": sum(int(row["retrieval_rounds"]) for row in successful),
        "retrieval_rounds_per_event": 1 if successful else 0,
    }


def repair_lookup(raw_predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index repair metadata by event id."""

    lookup = {}
    for row in raw_predictions:
        metadata = row.get("v5_metadata", {})
        proposals = metadata.get("repair_proposals", [])
        lookup[row["event_id"]] = {
            "repair_attempts": metadata.get("repair_attempts", 0),
            "added_nodes": [proposal["proposed_node"] for proposal in proposals],
            "projections": metadata.get("current_context_projections", {}),
            "proposals": {
                proposal["proposed_node"]: proposal for proposal in proposals
            },
        }
    return lookup


@contextmanager
def _prediction_projection_overrides(
    current_context_overrides: dict[str, dict[str, str]],
):
    """Temporarily expose V5 contexts to V4 snapshot row builders."""

    if not current_context_overrides:
        yield
        return

    import src.validation.v4_temporal_prediction as temporal_prediction

    original = temporal_prediction.project_current_event_context

    def projected_context(event: Any, node: str) -> dict[str, str] | None:
        return current_context_overrides.get(node) or original(event, node)

    temporal_prediction.project_current_event_context = projected_context
    try:
        yield
    finally:
        temporal_prediction.project_current_event_context = original


def compare_counters(v4: Counter, v5: Counter) -> list[dict[str, Any]]:
    """Return sorted V4/V5/delta rows for a counter."""

    keys = sorted(set(v4) | set(v5))
    return [
        {"label": key, "v4_count": v4[key], "v5_count": v5[key], "delta": v5[key] - v4[key]}
        for key in keys
    ]


def as_bool(value: Any) -> bool:
    """Parse bools that may have round-tripped through CSV."""

    if isinstance(value, bool):
        return value
    return str(value) == "True"


def _paths(output: Path) -> dict[str, Path]:
    return {
        "summary": output / SUMMARY_PATH.name,
        "funnel": output / FUNNEL_PATH.name,
        "event_results": output / EVENT_RESULTS_PATH.name,
        "trajectory_review": output / TRAJECTORY_REVIEW_PATH.name,
        "accepted_review": output / ACCEPTED_REVIEW_PATH.name,
        "mechanism_evaluation": output / MECHANISM_EVALUATION_PATH.name,
        "raw_predictions": output / RAW_PREDICTIONS_PATH.name,
        "node_snapshot": output / NODE_SNAPSHOT_PATH.name,
        "asset_snapshot": output / ASSET_SNAPSHOT_PATH.name,
    }


def _delta(v4: Any, v5: Any) -> Any:
    if isinstance(v4, (int, float)) and isinstance(v5, (int, float)):
        return round(v5 - v4, 6)
    return None


def rate(numerator: int, denominator: int) -> float | None:
    """Return a rounded rate or None for zero denominator."""

    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """Load CSV rows."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [{key: (value or "") for key, value in row.items()} for row in csv.DictReader(handle)]


def write_csv(
    path: str | Path,
    rows: list[dict[str, Any]],
    fields: list[str] | None = None,
) -> Path:
    """Write CSV rows."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fields or (list(rows[0].keys()) if rows else ["empty"])
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
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
