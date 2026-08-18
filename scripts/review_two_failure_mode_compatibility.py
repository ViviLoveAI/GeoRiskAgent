"""Review two structured-context false-rejection failure modes offline.

This script is diagnostic-only. It compares the original structured prototype
against a minimal review variant for two known clean-control false rejections,
without modifying production retrieval, KB, transmission logic, ranking, or CAR.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scripts.prototype_mechanism_compatible_support import (
    CASE_CONTEXTS,
    CURRENT_CONTEXTS,
    _ctx,
    _read_csv,
    _write_csv,
    _write_json,
)
from src.validation.transmission_context import (
    support_diagnostics,
    support_diagnostics_with_family_review,
)


INPUT = Path("data/topk_sensitivity_v4/mechanism_compatible_support_audit.csv")
OUTPUT = Path("data/topk_sensitivity_v4/two_failure_mode_compatibility_review.csv")
SUMMARY = Path("data/topk_sensitivity_v4/two_failure_mode_compatibility_review_summary.json")

DEFENSE_REANNOTATED_CONTEXTS = {
    ("eval_dutch_asml_export_controls", "defense"): _ctx(
        "defense", "export_restriction", "input_access_restriction",
        "semiconductor_supply_restriction", "downstream_strategic_exposure",
        "semiconductor_strategic_downstream_exposure",
    ),
    ("case_2024_taiwan_strait_drills_semiconductor_supply", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "advanced_foundry_concentration_risk", "downstream_strategic_exposure",
        "semiconductor_strategic_downstream_exposure",
    ),
    ("case_taiwan_strait_semiconductor_risk", "defense"): _ctx(
        "defense", "military_escalation", "security_risk",
        "advanced_chip_supply_uncertainty", "downstream_strategic_exposure",
        "semiconductor_strategic_downstream_exposure",
    ),
}


def main() -> None:
    """Run the two-failure-mode compatibility review."""

    rows = _read_csv(INPUT)
    reviewed = [_review_row(row) for row in rows]
    summary = _summary(reviewed)
    _write_csv(OUTPUT, reviewed)
    _write_json(SUMMARY, summary)
    print(json.dumps(summary["before_after"], indent=2, sort_keys=True))


def _review_row(row: dict[str, str]) -> dict[str, Any]:
    event_id = row["event_id"]
    node = row["node"]
    support_ids = _split(row["supporting_case_ids"])
    current_before = CURRENT_CONTEXTS.get((event_id, node))
    support_before = [
        {"case_id": case_id, **CASE_CONTEXTS[(case_id, node)]}
        for case_id in support_ids
        if (case_id, node) in CASE_CONTEXTS
    ]

    current_after = DEFENSE_REANNOTATED_CONTEXTS.get((event_id, node), current_before)
    support_after = [
        {
            "case_id": case_id,
            **DEFENSE_REANNOTATED_CONTEXTS.get(
                (case_id, node),
                CASE_CONTEXTS[(case_id, node)],
            ),
        }
        for case_id in support_ids
        if (case_id, node) in CASE_CONTEXTS
    ]

    before = support_diagnostics(current_before, support_before)
    after = support_diagnostics_with_family_review(current_after, support_after)
    target_keep = row["audit_label"] in {"consistent", "mixed"}

    return {
        **row,
        "after_result": _result_label(after),
        "after_compatible_support_count": after["compatible_support_count"],
        "after_incompatible_support_count": after["incompatible_support_count"],
        "after_insufficient_context_count": after["insufficient_context_count"],
        "after_compatible_case_ids": ";".join(after["compatible_case_ids"]),
        "after_incompatible_case_ids": ";".join(after["incompatible_case_ids"]),
        "after_case_decisions_json": json.dumps(after["case_decisions"], sort_keys=True),
        "target_keep": target_keep,
        "before_correct": before["candidate_under_structured_rule"] == target_keep,
        "after_correct": after["candidate_under_structured_rule"] == target_keep,
        "review_change_applied": _review_change(event_id, node),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    weak_rows = [row for row in rows if row["audit_label"] == "weak_cooccurrence"]
    nonweak_rows = [row for row in rows if row["audit_label"] in {"consistent", "mixed"}]
    clean_rows = [row for row in rows if row["source"] == "clean_control"]
    error_rows = [row for row in rows if row["source"] == "rule6_error"]
    two_failures = [
        row for row in rows
        if row["source"] == "clean_control"
        and row["structured_context_result"] == "reject"
    ]
    return {
        "diagnostic_only": True,
        "review_changes": {
            "canonical_context_family_hierarchy": [
                "maritime_route_capacity_constraint -> maritime_route_disruption",
                "maritime_route_security_constraint -> maritime_route_disruption",
                "oil_shipping_security_constraint -> maritime_route_disruption",
                "energy_chokepoint_security_constraint -> maritime_route_disruption",
                "energy_shipping_sanctions_route_constraint -> maritime_route_disruption",
                "semiconductor_input_access_constraint -> strategic_technology_downstream_exposure",
                "semiconductor_strategic_downstream_exposure -> strategic_technology_downstream_exposure",
            ],
            "active_role_compatibility": (
                "Different active-role subtypes may match when context family or "
                "constraint/active-role family is compatible; contextual_background "
                "remains non-voting."
            ),
            "defense_diagnostic_reannotation": (
                "Only eval_dutch_asml_export_controls/defense and its two Taiwan "
                "supporting cases are reannotated as downstream_strategic_exposure."
            ),
        },
        "two_false_rejections": [
            {
                "event_id": row["event_id"],
                "node": row["node"],
                "before": row["structured_context_result"],
                "after": row["after_result"],
                "before_compatible_support_count": row["compatible_support_count"],
                "after_compatible_support_count": row["after_compatible_support_count"],
                "after_compatible_case_ids": row["after_compatible_case_ids"],
                "review_change_applied": row["review_change_applied"],
            }
            for row in two_failures
        ],
        "before_after": {
            "known_rule6_errors_fixed": {
                "before": sum(row["structured_correct"] == "True" for row in error_rows),
                "after": sum(row["after_correct"] for row in error_rows),
            },
            "clean_controls_retained": {
                "before": sum(row["structured_context_result"] == "keep" for row in clean_rows),
                "after": sum(row["after_result"] == "keep" for row in clean_rows),
            },
            "clean_control_false_rejects": {
                "before": sum(
                    row["structured_context_result"] != "keep"
                    for row in clean_rows
                    if row["audit_label"] in {"consistent", "mixed"}
                ),
                "after": sum(
                    row["after_result"] != "keep"
                    for row in clean_rows
                    if row["audit_label"] in {"consistent", "mixed"}
                ),
            },
            "weak_cases_incorrectly_accepted": {
                "before": sum(row["structured_context_result"] == "keep" for row in weak_rows),
                "after": sum(row["after_result"] == "keep" for row in weak_rows),
            },
            "insufficient_context_cases": {
                "before": sum(row["structured_context_result"] == "insufficient_context" for row in rows),
                "after": sum(row["after_result"] == "insufficient_context" for row in rows),
            },
            "non_weak_retained": {
                "before": sum(row["structured_context_result"] == "keep" for row in nonweak_rows),
                "after": sum(row["after_result"] == "keep" for row in nonweak_rows),
            },
        },
        "weak_regression_rows": [
            {
                "event_id": row["event_id"],
                "node": row["node"],
                "after_result": row["after_result"],
                "after_compatible_case_ids": row["after_compatible_case_ids"],
            }
            for row in weak_rows
            if row["after_result"] == "keep"
        ],
    }


def _review_change(event_id: str, node: str) -> str:
    if event_id == "eval_cyber_port_pipeline_disruption" and node == "maritime_chokepoint":
        return "canonical_context_family_hierarchy_and_active_role_compatibility"
    if event_id == "eval_dutch_asml_export_controls" and node == "defense":
        return "downstream_strategic_exposure_reannotation"
    return "same_review_rule_no_instance_specific_reannotation"


def _result_label(diagnostics: dict[str, Any]) -> str:
    if diagnostics["candidate_under_structured_rule"]:
        return "keep"
    if diagnostics["compatible_support_count"] == 0 and diagnostics["insufficient_context_count"] > 0:
        return "insufficient_context"
    return "reject"


def _split(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


if __name__ == "__main__":
    main()
