"""Targeted provenance replay for legacy V3 CAR prediction snapshots.

This audit helper replays a small, fixed sample of frozen V3 CAR events with
the current fixed retrieval reconstruction. It writes comparison artifacts
under ``data/audits`` and never overwrites frozen V3, CAR, or market-validation
outputs.
"""

from __future__ import annotations

import csv
import json
import platform
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb

from src.config import ASSET_MAPPING_PATH, HISTORICAL_CASES_PATH
from src.pipeline import run_pipeline
from src.v3_config import V3_CONFIG


OUTPUT_DIR = Path("data/audits/v3_car_provenance_replay_20260815")
SNAPSHOT_DIR = Path("data/validation_v3/prediction_snapshots")
CAR_PAIR_RESULTS = Path("data/car_results_v3/car_pair_results.csv")

SELECTED_EVENTS = {
    "v3_20250404_china_rare_earth_export_controls": (
        "strong CAR-hit event with mostly sector-proxy outputs"
    ),
    "v3_20240223_sovcomflot_sanctions": (
        "several second-order exposures with historical-supported and sector-proxy mix"
    ),
    "v3_20240306_true_confidence_attack": (
        "Red Sea-style shipping event with second-order defense references and CAR misses"
    ),
    "v3_20241203_iran_shadow_fleet_sanctions": (
        "large mixed output set with direct and second-order energy/shipping exposures"
    ),
    "v3_20250225_copper_import_investigation": (
        "mostly sector-proxy/inference output and CAR miss case"
    ),
}


def main() -> None:
    """Run the targeted replay and write audit artifacts."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = load_selected_snapshots()
    car_rows = load_car_rows()
    comparisons = [
        compare_event(snapshot, car_rows.get(snapshot["event_id"], []))
        for snapshot in snapshots
    ]
    summary = {
        "audit_id": "v3_car_provenance_replay_20260815",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "targeted replay of representative legacy V3 CAR upstream prediction snapshots",
        "replay_config": replay_config(),
        "environment": environment_metadata(),
        "selected_events": [
            {
                "event_id": event_id,
                "selection_reason": SELECTED_EVENTS[event_id],
            }
            for event_id in SELECTED_EVENTS
        ],
        "comparisons": comparisons,
        "classification_counts": dict(Counter(row["classification"] for row in comparisons)),
        "overall_classification": overall_classification(comparisons),
    }
    write_json(OUTPUT_DIR / "replay_comparison.json", summary)
    write_csv(OUTPUT_DIR / "replay_summary.csv", [summary_row(row) for row in comparisons])
    print(json.dumps({
        "output_dir": str(OUTPUT_DIR),
        "overall_classification": summary["overall_classification"],
        "classification_counts": summary["classification_counts"],
    }, indent=2, sort_keys=True))


def load_selected_snapshots() -> list[dict[str, Any]]:
    """Load selected frozen V3 snapshots in the configured order."""

    snapshots = []
    for event_id in SELECTED_EVENTS:
        path = SNAPSHOT_DIR / f"{event_id}_snapshot_v3.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["legacy_snapshot_path"] = str(path)
        snapshots.append(snapshot)
    return snapshots


def load_car_rows() -> dict[str, list[dict[str, str]]]:
    """Load evaluated GeoRisk rows from the frozen V3 CAR result file."""

    if not CAR_PAIR_RESULTS.exists():
        return {}
    rows_by_event: dict[str, list[dict[str, str]]] = defaultdict(list)
    with CAR_PAIR_RESULTS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("source") != "georisk":
                continue
            if row.get("missing_data_reason"):
                continue
            rows_by_event[row["event_id"]].append(row)
    return dict(rows_by_event)


def compare_event(snapshot: dict[str, Any], car_rows: list[dict[str, str]]) -> dict[str, Any]:
    """Replay one event and compare frozen snapshot exposures with new output."""

    event_text = snapshot["event_description"]
    report = run_pipeline(
        event_text,
        top_k=V3_CONFIG.retrieval_top_k,
        event_analyzer=V3_CONFIG.event_analyzer,
    )
    old_exposures = list(snapshot.get("predicted_exposures", []))
    new_exposures = [exposure_from_result(snapshot["event_id"], result) for result in report.evidence_results]

    old_keys = exposure_key_set(old_exposures)
    new_keys = exposure_key_set(new_exposures)
    shared = sorted(old_keys & new_keys)
    old_only = sorted(old_keys - new_keys)
    new_only = sorted(new_keys - old_keys)
    evidence_diffs = evidence_differences(old_exposures, new_exposures, shared)
    car_keys = {
        (row.get("symbol", ""), row.get("node", ""))
        for row in car_rows
    }
    car_missing_in_replay = sorted(car_keys - new_keys)
    replay_extra_vs_car = sorted(new_keys - car_keys)
    retrieved_ids = [case.case_id for case in report.retrieved_cases]
    retrieved_node_coverage = [
        {
            "case_id": case.case_id,
            "supply_chain_nodes": list(case.supply_chain_nodes),
        }
        for case in report.retrieved_cases
    ]

    return {
        "event_id": snapshot["event_id"],
        "selection_reason": SELECTED_EVENTS[snapshot["event_id"]],
        "legacy_snapshot_path": snapshot["legacy_snapshot_path"],
        "original_input": event_text,
        "legacy_metadata": {
            "generated_at": snapshot.get("generated_at"),
            "snapshot_version": snapshot.get("snapshot_version"),
            "pipeline_mode": snapshot.get("pipeline_mode"),
            "event_analyzer_mode": snapshot.get("event_analyzer_mode"),
            "retrieval_configuration": snapshot.get("retrieval_configuration"),
            "git_commit": snapshot.get("git_commit"),
        },
        "old_retrieved_ids": list(snapshot.get("retrieved_case_ids", [])),
        "new_retrieved_ids": retrieved_ids,
        "retrieved_case_node_coverage": retrieved_node_coverage,
        "old_nodes": sorted({node for _, node in old_keys}),
        "new_nodes": sorted({node for _, node in new_keys}),
        "old_assets": sorted({symbol for symbol, _ in old_keys}),
        "new_assets": sorted({symbol for symbol, _ in new_keys}),
        "old_exposure_count": len(old_keys),
        "new_exposure_count": len(new_keys),
        "shared_exposures": [{"symbol": symbol, "node": node} for symbol, node in shared],
        "old_only_exposures": [{"symbol": symbol, "node": node} for symbol, node in old_only],
        "new_only_exposures": [{"symbol": symbol, "node": node} for symbol, node in new_only],
        "shared_count": len(shared),
        "old_only_count": len(old_only),
        "new_only_count": len(new_only),
        "jaccard_overlap": jaccard(old_keys, new_keys),
        "evidence_differences": evidence_diffs,
        "car_linkage": {
            "car_evaluated_old_exposures": [
                {"symbol": symbol, "node": node} for symbol, node in sorted(car_keys)
            ],
            "car_evaluated_count": len(car_keys),
            "car_missing_in_replay": [
                {"symbol": symbol, "node": node} for symbol, node in car_missing_in_replay
            ],
            "replay_extra_vs_car": [
                {"symbol": symbol, "node": node} for symbol, node in replay_extra_vs_car
            ],
        },
        "classification": classify_difference(old_keys, new_keys, evidence_diffs, car_missing_in_replay),
    }


def exposure_from_result(event_id: str, result: Any) -> dict[str, Any]:
    """Serialize the replay output into the legacy comparison shape."""

    return {
        "event_id": event_id,
        "symbol": result.ticker,
        "node": result.asset.supply_chain_node or "unknown",
        "asset_type": result.asset.asset_type or "unknown",
        "evidence_label": result.evidence_level,
        "confidence": result.confidence,
        "transmission_order": result.transmission_order,
        "linkage_tier": result.linkage_tier,
        "supporting_case_ids": list(result.supporting_case_ids),
        "ranking_scope": result.ranking_scope,
        "rank_within_order": result.rank_within_order,
    }


def exposure_key_set(exposures: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Return unique exposure identity keys as ``(symbol, node)``."""

    return {
        (str(row.get("symbol") or row.get("ticker") or ""), str(row.get("node") or ""))
        for row in exposures
        if row.get("symbol") or row.get("ticker")
    }


def exposure_lookup(exposures: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Index exposure rows by comparison key."""

    return {
        (str(row.get("symbol") or row.get("ticker") or ""), str(row.get("node") or "")): row
        for row in exposures
        if row.get("symbol") or row.get("ticker")
    }


def evidence_differences(
    old_exposures: list[dict[str, Any]],
    new_exposures: list[dict[str, Any]],
    shared_keys: list[tuple[str, str]],
) -> list[dict[str, str]]:
    """Return evidence-level changes for shared exposures."""

    old_by_key = exposure_lookup(old_exposures)
    new_by_key = exposure_lookup(new_exposures)
    diffs = []
    for symbol, node in shared_keys:
        old_label = str(old_by_key[(symbol, node)].get("evidence_label") or "")
        new_label = str(new_by_key[(symbol, node)].get("evidence_label") or "")
        old_order = str(old_by_key[(symbol, node)].get("transmission_order") or "")
        new_order = str(new_by_key[(symbol, node)].get("transmission_order") or "")
        if old_label != new_label or old_order != new_order:
            diffs.append(
                {
                    "symbol": symbol,
                    "node": node,
                    "old_evidence_label": old_label,
                    "new_evidence_label": new_label,
                    "old_transmission_order": old_order,
                    "new_transmission_order": new_order,
                }
            )
    return diffs


def classify_difference(
    old_keys: set[tuple[str, str]],
    new_keys: set[tuple[str, str]],
    evidence_diffs: list[dict[str, str]],
    car_missing_in_replay: list[tuple[str, str]],
) -> str:
    """Classify replay drift in a transparent, conservative way."""

    if old_keys == new_keys and not evidence_diffs:
        return "CONSISTENT"
    overlap = jaccard(old_keys, new_keys)
    if not car_missing_in_replay and overlap >= 0.9 and len(evidence_diffs) <= 1:
        return "CONSISTENT_WITH_MINOR_DRIFT"
    return "MATERIAL_DIFFERENCE"


def jaccard(left: set[tuple[str, str]], right: set[tuple[str, str]]) -> float:
    """Return Jaccard overlap for two exposure sets."""

    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def overall_classification(comparisons: list[dict[str, Any]]) -> str:
    """Summarize event-level classifications."""

    labels = Counter(row["classification"] for row in comparisons)
    if labels.get("MATERIAL_DIFFERENCE"):
        return "MATERIAL_UPSTREAM_DIFFERENCE"
    if labels.get("CONSISTENT_WITH_MINOR_DRIFT"):
        return "PROVENANCE_VERIFIED_WITH_MINOR_DRIFT"
    return "PROVENANCE_VERIFIED"


def summary_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return one compact CSV summary row."""

    return {
        "event_id": row["event_id"],
        "old_exposures": row["old_exposure_count"],
        "replay_exposures": row["new_exposure_count"],
        "shared": row["shared_count"],
        "old_only": row["old_only_count"],
        "replay_only": row["new_only_count"],
        "jaccard_overlap": row["jaccard_overlap"],
        "evidence_changes": len(row["evidence_differences"]),
        "car_evaluated_count": row["car_linkage"]["car_evaluated_count"],
        "car_missing_in_replay": len(row["car_linkage"]["car_missing_in_replay"]),
        "classification": row["classification"],
    }


def replay_config() -> dict[str, Any]:
    """Return recovered legacy V3 replay configuration."""

    return {
        "entrypoint": "src.pipeline.run_pipeline",
        "event_analyzer": V3_CONFIG.event_analyzer,
        "top_k": V3_CONFIG.retrieval_top_k,
        "support_basis": V3_CONFIG.support_basis,
        "support_threshold": V3_CONFIG.support_threshold,
        "mechanism_compatibility_enabled": V3_CONFIG.mechanism_compatibility_enabled,
        "retrieval_embedding_model": V3_CONFIG.retrieval_embedding_model,
        "historical_kb_path": V3_CONFIG.historical_kb_path,
        "uncertain_parameters": [
            "The exact uncommitted working-tree state used on 2026-08-05 is not recoverable from git history."
        ],
    }


def environment_metadata() -> dict[str, Any]:
    """Return safe, reproducibility-relevant environment metadata."""

    return {
        "python_version": platform.python_version(),
        "chromadb_version": chromadb.__version__,
        "git_commit": current_git_commit(),
        "working_tree_dirty": working_tree_dirty(),
        "historical_kb_case_count": len(json.loads(HISTORICAL_CASES_PATH.read_text(encoding="utf-8"))),
        "asset_mapping_row_count": sum(1 for _ in ASSET_MAPPING_PATH.open(encoding="utf-8")) - 1,
        "bug_fix_status": "RetrievedCase.supply_chain_nodes carried through in src.vector_store.query_cases",
    }


def current_git_commit() -> str:
    """Return the current git commit if available."""

    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def working_tree_dirty() -> bool:
    """Return whether there are local modifications."""

    try:
        output = subprocess.check_output(["git", "status", "--porcelain"], text=True)
    except Exception:
        return True
    return bool(output.strip())


def write_json(path: Path, payload: Any) -> None:
    """Write stable JSON."""

    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a CSV file."""

    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
