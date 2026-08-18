"""Offline Top-K sensitivity diagnostic for second-order candidate generation.

This script is intentionally diagnostic-only. It keeps the current GeoRisk
pipeline behavior fixed and varies only retrieval top_k to inspect how the
second-order candidate funnel changes.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.audit_upstream_candidates import (
    DEFAULT_ASSET_MAPPING,
    DEFAULT_V3_MANIFEST,
    _audit_event,
    _funnel_summary,
    _load_evaluation_events,
    _load_json,
    _load_v3_events,
    _node_to_kb_cases,
    _retrieval_metrics,
)
from src.config import HISTORICAL_CASES_PATH


DEFAULT_OUTPUT_DIR = Path("data/topk_sensitivity_v4")
TOP_K_VALUES = [3, 5, 10]


def main() -> None:
    """Run the offline Top-K sensitivity experiment."""

    parser = argparse.ArgumentParser(
        description="Compare second-order candidate funnels across retrieval top_k values."
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        default=TOP_K_VALUES,
        help="Top-K values to compare. Defaults to 3 5 10.",
    )
    parser.add_argument("--v3-manifest", default=str(DEFAULT_V3_MANIFEST))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = _load_json(HISTORICAL_CASES_PATH)
    cases_by_id = {case["event_id"]: case for case in cases}
    node_to_kb_cases = _node_to_kb_cases(cases)
    mapping = pd.read_csv(DEFAULT_ASSET_MAPPING)
    mapped_nodes = set(mapping["supply_chain_node"].astype(str))

    eval_events = _load_evaluation_events()
    v3_events = _load_v3_events(Path(args.v3_manifest))
    events = [*eval_events, *v3_events]

    results_by_k: dict[int, dict[str, Any]] = {}
    comparison_rows: list[dict[str, Any]] = []

    for top_k in sorted(set(args.top_k)):
        event_rows: list[dict[str, Any]] = []
        retrieval_rows: list[dict[str, Any]] = []
        node_rows: list[dict[str, Any]] = []
        exposure_rows: list[dict[str, Any]] = []

        for event_record in events:
            audit = _audit_event(
                event_record=event_record,
                top_k=top_k,
                cases_by_id=cases_by_id,
                node_to_kb_cases=node_to_kb_cases,
                mapped_nodes=mapped_nodes,
            )
            event_rows.append(audit["event_row"])
            retrieval_rows.extend(audit["retrieval_rows"])
            node_rows.extend(audit["node_rows"])
            exposure_rows.extend(audit["exposure_rows"])

        retrieval_metrics = _retrieval_metrics(retrieval_rows, eval_events, top_k=top_k)
        funnel = _funnel_summary(event_rows, node_rows, exposure_rows)
        threshold_misses = sum(
            1 for row in node_rows if row["potential_retrieval_bottleneck"]
        )
        evidence_counts = Counter(row["evidence_level"] for row in exposure_rows)

        results_by_k[top_k] = {
            "event_rows": event_rows,
            "retrieval_rows": retrieval_rows,
            "node_rows": node_rows,
            "exposure_rows": exposure_rows,
            "retrieval_metrics": retrieval_metrics,
            "funnel": funnel,
            "threshold_misses": threshold_misses,
        }

        comparison_rows.append(
            {
                "top_k": top_k,
                "events_evaluated": len(events),
                "retrieved_cases": len(retrieval_rows),
                "recall_at_1": retrieval_metrics.get("recall_at_1"),
                "recall_at_3": retrieval_metrics.get("recall_at_3"),
                f"recall_at_{top_k}": retrieval_metrics.get(f"recall_at_{top_k}"),
                "mrr": retrieval_metrics.get("mrr"),
                "raw_unique_second_order_nodes": funnel["unique_raw_second_order_nodes"],
                "raw_second_order_nodes": funnel["raw_second_order_nodes"],
                "support_qualified_nodes": funnel["accepted_second_order_nodes"],
                "nodes_failing_support_threshold": funnel["dropped_by_support_requirement"],
                "retrieval_limited_threshold_misses": threshold_misses,
                "nodes_sent_to_mapper": funnel["supported_nodes_sent_to_market_mapper"],
                "mapped_nodes": funnel["mapped_second_order_nodes"],
                "unmapped_nodes": funnel["unmapped_accepted_second_order_nodes"],
                "mapping_coverage": funnel["node_mapping_coverage"],
                "historical_supported": evidence_counts.get("historical_supported", 0),
                "sector_proxy": evidence_counts.get("sector_proxy", 0),
                "inference_only": evidence_counts.get("inference_only", 0),
                "second_order_assets": funnel["second_order_assets"],
                "ranked_second_order_assets": funnel["v4_ranked_second_order_candidates"],
                "unique_ranked_tickers": len(
                    {row["ticker"] for row in exposure_rows if row["ranking_scope"] == "ranked_second_order"}
                ),
                "historical_supported_share": _share(
                    evidence_counts.get("historical_supported", 0),
                    funnel["second_order_assets"],
                ),
                "sector_proxy_share": _share(
                    evidence_counts.get("sector_proxy", 0),
                    funnel["second_order_assets"],
                ),
                "inference_only_share": _share(
                    evidence_counts.get("inference_only", 0),
                    funnel["second_order_assets"],
                ),
            }
        )

        _write_csv(output_dir / f"event_funnel_k{top_k}.csv", event_rows)
        _write_csv(output_dir / f"second_order_nodes_k{top_k}.csv", node_rows)
        _write_csv(output_dir / f"second_order_assets_k{top_k}.csv", exposure_rows)

    increment_rows = _incremental_candidates(results_by_k)
    funnel_rows = _funnel_rows(results_by_k)
    summary = _summary_payload(comparison_rows, increment_rows)

    _write_csv(output_dir / "topk_comparison.csv", comparison_rows)
    _write_csv(output_dir / "incremental_candidates.csv", increment_rows)
    _write_csv(output_dir / "candidate_funnel_by_k.csv", funnel_rows)
    _write_json(output_dir / "topk_sensitivity_summary.json", summary)
    _write_markdown_report(output_dir / "TOPK_SENSITIVITY_REPORT.md", summary)

    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "top_k_values": sorted(results_by_k),
                "comparison": comparison_rows,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _incremental_candidates(results_by_k: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = sorted(results_by_k)
    for previous, current in zip(ordered, ordered[1:]):
        previous_keys = {
            _candidate_key(row)
            for row in results_by_k[previous]["exposure_rows"]
        }
        current_rows = results_by_k[current]["exposure_rows"]
        new_rows = [row for row in current_rows if _candidate_key(row) not in previous_keys]
        node_lookup = {
            (row["event_id"], row["node"]): row
            for row in results_by_k[current]["node_rows"]
        }
        for row in sorted(new_rows, key=lambda item: (item["event_id"], item["node"], item["ticker"])):
            node = node_lookup.get((row["event_id"], row["node"]), {})
            rows.append(
                {
                    "comparison": f"k{previous}_to_k{current}",
                    "from_k": previous,
                    "to_k": current,
                    "event_id": row["event_id"],
                    "event_name": row["event_name"],
                    "node": row["node"],
                    "ticker": row["ticker"],
                    "asset_name": row["asset_name"],
                    "asset_type": row["asset_type"],
                    "linkage_tier": row["linkage_tier"],
                    "supporting_case_ids": row["supporting_case_ids"],
                    "support_count": len([case for case in row["supporting_case_ids"].split(";") if case]),
                    "node_retrieved_supporting_case_ids": node.get("retrieved_supporting_case_ids", ""),
                    "node_retrieved_support_count": node.get("retrieved_supporting_case_count", ""),
                    "retrieved_supporting_case_count": node.get("retrieved_supporting_case_count", ""),
                    "evidence_level": row["evidence_level"],
                    "mapping_status": "mapped",
                }
            )
    return rows


def _funnel_rows(results_by_k: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for top_k, result in sorted(results_by_k.items()):
        funnel = result["funnel"]
        evidence = funnel["evidence_grading"]
        rows.append(
            {
                "top_k": top_k,
                "retrieved_cases": len(result["retrieval_rows"]),
                "support_qualified_second_order_nodes": funnel["accepted_second_order_nodes"],
                "mapped_nodes": funnel["mapped_second_order_nodes"],
                "second_order_assets": funnel["second_order_assets"],
                "historical_supported": evidence.get("historical_supported", 0),
                "sector_proxy": evidence.get("sector_proxy", 0),
                "inference_only": evidence.get("inference_only", 0),
                "v4_ranked_candidates": funnel["v4_ranked_second_order_candidates"],
            }
        )
    return rows


def _summary_payload(
    comparison_rows: list[dict[str, Any]],
    increment_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    comparisons = {int(row["top_k"]): row for row in comparison_rows}
    deltas = []
    ordered = sorted(comparisons)
    for previous, current in zip(ordered, ordered[1:]):
        prev = comparisons[previous]
        curr = comparisons[current]
        deltas.append(
            {
                "comparison": f"k{previous}_to_k{current}",
                "threshold_miss_reduction": (
                    prev["retrieval_limited_threshold_misses"]
                    - curr["retrieval_limited_threshold_misses"]
                ),
                "qualified_node_increase": (
                    curr["support_qualified_nodes"] - prev["support_qualified_nodes"]
                ),
                "mapped_asset_increase": (
                    curr["second_order_assets"] - prev["second_order_assets"]
                ),
                "new_candidate_count": sum(
                    1 for row in increment_rows if row["comparison"] == f"k{previous}_to_k{current}"
                ),
            }
        )
    return {
        "topk_comparison": comparison_rows,
        "deltas": deltas,
        "incremental_candidate_count_by_step": dict(
            Counter(row["comparison"] for row in increment_rows)
        ),
    }


def _candidate_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (row["event_id"], row["node"], row["ticker"])


def _share(count: int, total: int) -> float | None:
    return count / total if total else None


def _write_markdown_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Offline Top-K Sensitivity Diagnostic",
        "",
        "Only retrieval top_k varies in this diagnostic; production configuration is unchanged.",
        "",
        "## Top-K Comparison",
        "",
        "```json",
        json.dumps(summary["topk_comparison"], indent=2, sort_keys=True),
        "```",
        "",
        "## Deltas",
        "",
        "```json",
        json.dumps(summary["deltas"], indent=2, sort_keys=True),
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
