"""Review the development annotation for food-export agriculture support.

Diagnostic-only. This script audits whether the development label for
`dev_food_export_restriction / agriculture` matches the causal-mechanism
compatibility definition. It does not change production behavior, retrieval,
context schema, compatibility rules, market data, or CAR outputs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scripts.validate_mechanism_freeze_candidate import (
    EXPANDED_CASE_CONTEXTS,
    EXPANDED_CURRENT_CONTEXTS,
)
from src.validation.transmission_context import (
    COMPATIBLE,
    REVIEW_CANONICAL_CONTEXT_FAMILIES,
    mechanism_compatibility_with_family_review,
)


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
OUTPUT_CSV = OUTPUT_DIR / "agriculture_annotation_review.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / "agriculture_annotation_review_summary.json"


def main() -> None:
    rows = [_review_pair(pair) for pair in _review_pairs()]
    summary = _summary(rows)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(OUTPUT_CSV, rows)
    OUTPUT_SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, indent=2, sort_keys=True))


def _review_pairs() -> list[dict[str, Any]]:
    current_agriculture = EXPANDED_CURRENT_CONTEXTS[
        ("dev_food_export_restriction", "agriculture")
    ]
    current_grain = EXPANDED_CURRENT_CONTEXTS[
        ("dev_food_export_restriction", "grain_exports")
    ]
    fertilizer_1 = EXPANDED_CASE_CONTEXTS[
        ("case_2021_belarus_potash_sanctions", "agriculture")
    ]
    fertilizer_2 = EXPANDED_CASE_CONTEXTS[
        ("case_2022_russia_fertilizer_export_restrictions", "agriculture")
    ]
    food_export_1 = EXPANDED_CASE_CONTEXTS[
        ("case_2022_india_wheat_export_ban", "grain_exports")
    ]
    food_export_2 = EXPANDED_CASE_CONTEXTS[
        ("case_2008_rice_export_restrictions_food_security", "grain_exports")
    ]

    return [
        _pair(
            "target_belarus_potash",
            "dev_food_export_restriction",
            "agriculture",
            "case_2021_belarus_potash_sanctions",
            current_agriculture,
            fertilizer_1,
            "compatible_expected",
            "change_to_weak_cooccurrence_expected",
            False,
            (
                "Food export restrictions affect export availability and trade access; "
                "potash sanctions affect farm input availability and production-cost "
                "pressure. They share agriculture as a node but not the causal "
                "transmission process."
            ),
            "high",
        ),
        _pair(
            "target_russia_fertilizer",
            "dev_food_export_restriction",
            "agriculture",
            "case_2022_russia_fertilizer_export_restrictions",
            current_agriculture,
            fertilizer_2,
            "compatible_expected",
            "change_to_weak_cooccurrence_expected",
            False,
            (
                "The current case is a finished-food or grain export trade constraint; "
                "the support case is an agricultural input-shortage mechanism through "
                "fertilizer. Same downstream node is insufficient for support."
            ),
            "high",
        ),
        _pair(
            "positive_food_export_india",
            "dev_food_export_restriction",
            "grain_exports",
            "case_2022_india_wheat_export_ban",
            current_grain,
            food_export_1,
            "compatible_control",
            "keep_compatible",
            True,
            "Both contexts describe food/grain export trade restrictions.",
            "high",
        ),
        _pair(
            "positive_food_export_rice",
            "dev_food_export_restriction",
            "grain_exports",
            "case_2008_rice_export_restrictions_food_security",
            current_grain,
            food_export_2,
            "compatible_control",
            "keep_compatible",
            True,
            "Both contexts describe food/grain export controls constraining trade flows.",
            "high",
        ),
        _pair(
            "positive_fertilizer_input",
            "fertilizer_input_control",
            "agriculture",
            "case_2022_russia_fertilizer_export_restrictions",
            fertilizer_1,
            fertilizer_2,
            "compatible_control",
            "keep_compatible",
            True,
            "Both contexts describe fertilizer/input restrictions transmitting into agriculture.",
            "high",
        ),
        _pair(
            "cross_food_export_to_fertilizer",
            "dev_food_export_restriction",
            "agriculture",
            "case_2022_russia_fertilizer_export_restrictions",
            current_agriculture,
            fertilizer_2,
            "negative_control",
            "keep_incompatible",
            False,
            "Food export trade access and fertilizer input shortage are related but distinct.",
            "high",
        ),
    ]


def _pair(
    review_case_id: str,
    current_event_id: str,
    current_node: str,
    historical_case_id: str,
    current_context: dict[str, Any],
    historical_context: dict[str, Any],
    current_label: str,
    reviewer_recommendation: str,
    shared_transmission_process: bool,
    rationale: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "review_case_id": review_case_id,
        "current_event_id": current_event_id,
        "current_node": current_node,
        "historical_case_id": historical_case_id,
        "current_context": current_context,
        "historical_context": historical_context,
        "current_label": current_label,
        "reviewer_recommendation": reviewer_recommendation,
        "shared_transmission_process": shared_transmission_process,
        "rationale": rationale,
        "confidence": confidence,
    }


def _review_pair(pair: dict[str, Any]) -> dict[str, Any]:
    current = pair["current_context"]
    historical = pair["historical_context"]
    decision = mechanism_compatibility_with_family_review(current, historical)
    same_exact = current["canonical_context"] == historical["canonical_context"]
    same_family = _family(current["canonical_context"]) == _family(historical["canonical_context"])
    return {
        "review_case_id": pair["review_case_id"],
        "current_event_id": pair["current_event_id"],
        "current_node": pair["current_node"],
        "historical_case_id": pair["historical_case_id"],
        "current_canonical_context": current["canonical_context"],
        "historical_canonical_context": historical["canonical_context"],
        "current_constraint_type": current["constraint_type"],
        "historical_constraint_type": historical["constraint_type"],
        "current_upstream_driver": current["upstream_driver"],
        "historical_upstream_driver": historical["upstream_driver"],
        "current_target_node_role": current["target_node_role"],
        "historical_target_node_role": historical["target_node_role"],
        "same_node": current.get("node") == historical.get("node"),
        "same_exact_mechanism": same_exact,
        "same_canonical_family": same_family,
        "shared_transmission_process": pair["shared_transmission_process"],
        "diagnostic_compatible": decision.status == COMPATIBLE,
        "diagnostic_reason": decision.reason,
        "current_label": pair["current_label"],
        "reviewer_recommendation": pair["reviewer_recommendation"],
        "rationale": pair["rationale"],
        "confidence": pair["confidence"],
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_rows = [
        row for row in rows
        if row["review_case_id"].startswith("target_")
    ]
    return {
        "diagnostic_only": True,
        "review_scope": "dev_food_export_restriction / agriculture only",
        "current_label": "compatible_support_expected",
        "recommended_label": "weak_cooccurrence_expected",
        "review_outcome": "ground_truth_granularity_correction",
        "system_rejection_likely_correct": True,
        "rule_change_recommended": False,
        "new_family_abstraction_recommended": False,
        "target_pairs_reviewed": len(target_rows),
        "target_pairs_shared_transmission_process": sum(
            row["shared_transmission_process"] for row in target_rows
        ),
        "target_pairs_diagnostic_compatible": sum(
            row["diagnostic_compatible"] for row in target_rows
        ),
        "positive_controls_passed": sum(
            row["diagnostic_compatible"]
            for row in rows
            if row["current_label"] == "compatible_control"
        ),
        "positive_controls_total": sum(
            row["current_label"] == "compatible_control" for row in rows
        ),
        "negative_controls_rejected": sum(
            not row["diagnostic_compatible"]
            for row in rows
            if row["current_label"] == "negative_control"
        ),
        "negative_controls_total": sum(
            row["current_label"] == "negative_control" for row in rows
        ),
        "rationale": (
            "The original label groups food-export trade restrictions with fertilizer "
            "input constraints because both affect agriculture. Under the frozen "
            "causal-mechanism definition, this is too broad: same affected node does "
            "not establish mechanism-compatible historical support."
        ),
    }


def _family(canonical_context: str) -> str:
    return REVIEW_CANONICAL_CONTEXT_FAMILIES.get(canonical_context, canonical_context)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
