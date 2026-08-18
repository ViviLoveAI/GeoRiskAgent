"""Console reporting helpers for CAR validation."""

from __future__ import annotations

import pandas as pd


def print_summary(report: pd.DataFrame) -> None:
    """Print a concise validation summary to stdout."""

    evaluated = report[report["missing_data_reason"].fillna("") == ""]
    skipped = report[report["missing_data_reason"].fillna("") != ""]
    georisk_evaluated = evaluated[evaluated.get("group", "") == "georisk_flagged"]
    georisk_skipped = skipped[skipped.get("group", "") == "georisk_flagged"]
    baseline_evaluated = evaluated[evaluated.get("group", "") == "baseline"]
    baseline_skipped = skipped[skipped.get("group", "") == "baseline"]
    has_baseline = "baseline" in set(report.get("group", []))

    print("GeoRisk CAR Validation Summary")
    print("Scope: ex-post exposure validation only; no price prediction or advice.")
    print(f"events_evaluated: {report['event_id'].nunique()}")
    print(f"total_evaluated_pairs: {len(evaluated)}")
    print(f"skipped_pairs: {len(skipped)}")
    print(f"georisk_evaluated_pairs: {len(georisk_evaluated)}")
    print(f"georisk_skipped_pairs: {len(georisk_skipped)}")
    print(f"baseline_evaluated_pairs: {len(baseline_evaluated)}")
    print(f"baseline_skipped_pairs: {len(baseline_skipped)}")
    print(f"unique_symbols_evaluated: {evaluated['symbol'].nunique()}")
    print(f"unique_symbols_skipped: {skipped['symbol'].nunique()}")
    print(f"assets_evaluated: {len(evaluated)}")
    print(f"assets_skipped_due_to_missing_data: {len(skipped)}")
    print(f"exposure_hit_rate: {_hit_rate(evaluated):.2f}")
    print(f"georisk_flagged_hit_rate: {_hit_rate(georisk_evaluated):.2f}")
    if has_baseline:
        print(f"baseline_hit_rate: {_hit_rate(baseline_evaluated):.2f}")

    if "evidence_label" in georisk_evaluated.columns and not georisk_evaluated.empty:
        print("hit_rate_by_evidence_label_georisk_flagged:")
        for label, group in georisk_evaluated.groupby("evidence_label", dropna=False):
            print(f"  {label}: {_hit_rate(group):.2f} ({len(group)})")

    if "node" in georisk_evaluated.columns and not georisk_evaluated.empty:
        print("hit_rate_by_node_georisk_flagged:")
        for node, group in georisk_evaluated.groupby("node", dropna=False):
            print(f"  {node}: {_hit_rate(group):.2f} ({len(group)})")

    if "node" in baseline_evaluated.columns and not baseline_evaluated.empty:
        print("hit_rate_by_node_baseline:")
        for node, group in baseline_evaluated.groupby("node", dropna=False):
            print(f"  {node}: {_hit_rate(group):.2f} ({len(group)})")

    if "baseline_type" in baseline_evaluated.columns and not baseline_evaluated.empty:
        print("hit_rate_by_baseline_type:")
        for baseline_type, group in baseline_evaluated.groupby("baseline_type", dropna=False):
            print(f"  {baseline_type}: {_hit_rate(group):.2f} ({len(group)})")


def _hit_rate(frame: pd.DataFrame) -> float:
    """Return mean hit rate for evaluated rows."""

    if frame.empty:
        return 0.0
    return float(frame["hit"].astype(bool).mean())
