"""Compare legacy node support with V4 mechanism-compatible support.

The script is an offline shadow diagnostic. It does not alter user-facing
pipeline output and does not read CAR, prices, returns, or held-out results.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.validate_mechanism_freeze_candidate import (
    EXPANDED_CURRENT_CONTEXTS,
    EXPANDED_INSTANCES,
    _missing_context,
)
from src.agents.transmission_builder import MIN_CASE_SUPPORT_FOR_SECOND_ORDER
from src.mechanism_context import (
    CANONICAL_FAMILY_VERSION,
    MECHANISM_COMPATIBILITY_VERSION,
    TRANSMISSION_CONTEXT_VERSION,
    support_diagnostics,
)
from src.transmission_context_store import load_historical_contexts


OUTPUT_DIR = Path("data/topk_sensitivity_v4")
OUTPUT_CSV = OUTPUT_DIR / "production_shadow_comparison.csv"
OUTPUT_SUMMARY = OUTPUT_DIR / "production_shadow_comparison_summary.json"


def main() -> None:
    historical_contexts = load_historical_contexts()
    rows = [_shadow_row(instance, historical_contexts) for instance in EXPANDED_INSTANCES]
    summary = _summary(rows)
    _write_csv(OUTPUT_CSV, rows)
    OUTPUT_SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary, indent=2, sort_keys=True))


def _shadow_row(
    instance: dict[str, Any],
    historical_contexts: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    event_id = instance["event_id"]
    node = instance["node"]
    support_ids = instance["supporting_case_ids"]
    support_contexts = [
        {
            "case_id": case_id,
            **historical_contexts.get((case_id, node), _missing_context(node)),
        }
        for case_id in support_ids
    ]
    diagnostics = support_diagnostics(
        EXPANDED_CURRENT_CONTEXTS.get((event_id, node)),
        support_contexts,
        minimum_support=MIN_CASE_SUPPORT_FOR_SECOND_ORDER,
    )
    legacy_support_count = len(set(support_ids))
    legacy_keep = legacy_support_count >= MIN_CASE_SUPPORT_FOR_SECOND_ORDER
    v4_keep = diagnostics["candidate_under_structured_rule"]
    return {
        "event_id": event_id,
        "node": node,
        "mechanism_target": instance["mechanism_target"],
        "legacy_support_count": legacy_support_count,
        "mechanism_compatible_support_count": diagnostics["compatible_support_count"],
        "exact_support_count": diagnostics["exact_support_count"],
        "canonical_family_support_count": diagnostics["canonical_family_support_count"],
        "insufficient_context_count": diagnostics["insufficient_context_count"],
        "legacy_keep": legacy_keep,
        "v4_keep": v4_keep,
        "decision_changed": legacy_keep != v4_keep,
        "change_reason": _change_reason(legacy_keep, v4_keep, diagnostics),
        "compatible_case_ids": ";".join(diagnostics["compatible_case_ids"]),
        "incompatible_case_ids": ";".join(diagnostics["incompatible_case_ids"]),
        "insufficient_context_case_ids": ";".join(diagnostics["insufficient_context_case_ids"]),
    }


def _change_reason(
    legacy_keep: bool,
    v4_keep: bool,
    diagnostics: dict[str, Any],
) -> str:
    if legacy_keep == v4_keep:
        return "unchanged"
    if legacy_keep and not v4_keep:
        if diagnostics["insufficient_context_count"]:
            return "legacy_raw_node_vote_lacks_sufficient_mechanism_context"
        return "raw_node_cooccurrence_not_mechanism_compatible"
    return "mechanism_compatible_support_recovers_candidate"


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changed = [row for row in rows if row["decision_changed"]]
    legacy_to_reject = [
        row for row in rows if row["legacy_keep"] and not row["v4_keep"]
    ]
    reject_to_v4 = [
        row for row in rows if not row["legacy_keep"] and row["v4_keep"]
    ]
    return {
        "diagnostic_only": True,
        "transmission_context_version": TRANSMISSION_CONTEXT_VERSION,
        "canonical_family_version": CANONICAL_FAMILY_VERSION,
        "mechanism_compatibility_version": MECHANISM_COMPATIBILITY_VERSION,
        "support_threshold": MIN_CASE_SUPPORT_FOR_SECOND_ORDER,
        "total_node_decisions": len(rows),
        "unchanged_decisions": len(rows) - len(changed),
        "legacy_keep_to_v4_reject": len(legacy_to_reject),
        "legacy_reject_to_v4_keep": len(reject_to_v4),
        "insufficient_context_decisions": sum(
            row["insufficient_context_count"] > 0 for row in rows
        ),
        "exact_support_usage": sum(row["exact_support_count"] > 0 for row in rows),
        "family_support_usage": sum(row["canonical_family_support_count"] > 0 for row in rows),
        "change_reason_counts": dict(Counter(row["change_reason"] for row in rows)),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
