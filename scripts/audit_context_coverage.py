"""Audit node-level transmission-context coverage for V4 diagnostics.

This script is diagnostic-only. It reads the expanded development validation
contexts and reports whether relevant current-event and historical case/node
contexts are populated with informative values. It does not change production
retrieval, transmission building, evidence grading, ranking, market data, or
CAR outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.validate_mechanism_freeze_candidate import (
    EXPANDED_CASE_CONTEXTS,
    EXPANDED_CURRENT_CONTEXTS,
    EXPANDED_INSTANCES,
)
from src.validation.transmission_context import UNKNOWN_VALUES


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
REQUIRED_CONTEXT_FIELDS = [
    "shock_type",
    "constraint_type",
    "upstream_driver",
    "target_node_role",
    "canonical_context",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit expanded-validation transmission-context coverage.",
    )
    parser.add_argument(
        "--output-stem",
        default="context_coverage_audit",
        help="Output file stem under data/topk_sensitivity_v4.",
    )
    args = parser.parse_args()

    rows = build_context_coverage_rows()
    summary = summarize_context_coverage(rows)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f"{args.output_stem}.csv"
    summary_path = OUTPUT_DIR / f"{args.output_stem}_summary.json"
    _write_csv(csv_path, rows)
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def build_context_coverage_rows() -> list[dict[str, Any]]:
    """Return row-level coverage for all expanded-validation relevant nodes."""

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for instance in EXPANDED_INSTANCES:
        event_id = instance["event_id"]
        node = instance["node"]
        current_key = ("current_event_projection", event_id, "", node)
        if current_key not in seen:
            rows.append(
                _coverage_row(
                    source_type="current_event_projection",
                    event_id=event_id,
                    case_id="",
                    node=node,
                    context=EXPANDED_CURRENT_CONTEXTS.get((event_id, node)),
                )
            )
            seen.add(current_key)

        for case_id in instance["supporting_case_ids"]:
            historical_key = ("historical_case", "", case_id, node)
            if historical_key in seen:
                continue
            rows.append(
                _coverage_row(
                    source_type="historical_case",
                    event_id="",
                    case_id=case_id,
                    node=node,
                    context=EXPANDED_CASE_CONTEXTS.get((case_id, node)),
                )
            )
            seen.add(historical_key)
    return rows


def summarize_context_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize source-level and field-level informative coverage."""

    historical = [row for row in rows if row["source_type"] == "historical_case"]
    current = [row for row in rows if row["source_type"] == "current_event_projection"]
    return {
        "diagnostic_only": True,
        "scope": "expanded_validation_set",
        "required_context_fields": REQUIRED_CONTEXT_FIELDS,
        "total_relevant_nodes": len(rows),
        "historical_relevant_nodes": len(historical),
        "current_event_relevant_nodes": len(current),
        "historical_informative_coverage": _node_coverage(historical),
        "current_event_informative_coverage": _node_coverage(current),
        "overall_informative_coverage": _node_coverage(rows),
        "field_coverage": {
            field: _field_coverage(rows, field)
            for field in REQUIRED_CONTEXT_FIELDS
        },
        "field_coverage_by_source": {
            "historical_case": {
                field: _field_coverage(historical, field)
                for field in REQUIRED_CONTEXT_FIELDS
            },
            "current_event_projection": {
                field: _field_coverage(current, field)
                for field in REQUIRED_CONTEXT_FIELDS
            },
        },
        "missing_node_count": sum(row["gap_type"] == "missing_context" for row in rows),
        "partial_node_count": sum(row["gap_type"] == "partial_context" for row in rows),
        "fully_covered_node_count": sum(row["gap_type"] == "fully_covered" for row in rows),
        "gap_type_counts": dict(Counter(row["gap_type"] for row in rows)),
        "gaps": [
            row for row in rows if row["gap_type"] != "fully_covered"
        ],
    }


def _coverage_row(
    *,
    source_type: str,
    event_id: str,
    case_id: str,
    node: str,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    missing_fields = [
        field for field in REQUIRED_CONTEXT_FIELDS
        if context is None or field not in context
    ]
    non_informative_fields = [
        field for field in REQUIRED_CONTEXT_FIELDS
        if context is None or _non_informative(context.get(field))
    ]
    if context is None:
        gap_type = "missing_context"
    elif len(non_informative_fields) == len(REQUIRED_CONTEXT_FIELDS):
        gap_type = "missing_context"
    elif non_informative_fields:
        gap_type = "partial_context"
    else:
        gap_type = "fully_covered"

    return {
        "source_type": source_type,
        "event_id": event_id,
        "case_id": case_id,
        "node": node,
        "has_context": context is not None,
        "missing_fields": ";".join(missing_fields),
        "non_informative_fields": ";".join(non_informative_fields),
        "gap_type": gap_type,
        "notes": _notes(source_type, event_id, case_id, node, context, non_informative_fields),
    }


def _notes(
    source_type: str,
    event_id: str,
    case_id: str,
    node: str,
    context: dict[str, Any] | None,
    non_informative_fields: list[str],
) -> str:
    subject = event_id if source_type == "current_event_projection" else case_id
    if context is None:
        return f"{source_type} context is absent for {subject} / {node}"
    if non_informative_fields:
        return f"{source_type} context has non-informative values for {subject} / {node}"
    return "all required node-level context fields are informative"


def _node_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    covered = sum(row["gap_type"] == "fully_covered" for row in rows)
    return {
        "covered": covered,
        "total": len(rows),
        "coverage": round(covered / len(rows), 6) if rows else 0.0,
    }


def _field_coverage(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    informative = 0
    for row in rows:
        source_type = row["source_type"]
        context = _lookup_context(source_type, row["event_id"], row["case_id"], row["node"])
        if context is not None and not _non_informative(context.get(field)):
            informative += 1
    return {
        "informative": informative,
        "total": len(rows),
        "coverage": round(informative / len(rows), 6) if rows else 0.0,
    }


def _lookup_context(
    source_type: str,
    event_id: str,
    case_id: str,
    node: str,
) -> dict[str, Any] | None:
    if source_type == "current_event_projection":
        return EXPANDED_CURRENT_CONTEXTS.get((event_id, node))
    return EXPANDED_CASE_CONTEXTS.get((case_id, node))


def _non_informative(value: Any) -> bool:
    return value in UNKNOWN_VALUES


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
