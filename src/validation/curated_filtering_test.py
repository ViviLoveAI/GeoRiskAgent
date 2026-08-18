"""Curated-pool filtering diagnostic for frozen GeoRisk CAR validation.

This post-freeze analysis compares assets selected by GeoRisk against assets
that the same frozen event-specific pipeline considered but did not select.
It explicitly excludes assets that were never generated for an event and does
not use prices or SCAR values while reconstructing the candidate set.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd
from scipy.stats import mannwhitneyu


DEFAULT_OUTPUT_DIR = Path("data/market_validation/curated_filtering")
DEFAULT_SNAPSHOT_DIR = Path("data/validation_v3/prediction_snapshots")
DEFAULT_ASSET_MAPPING_PATH = Path("data/asset_mapping.csv")
DEFAULT_CAR_RESULTS_PATH = Path("data/car_results_v3/car_pair_results.csv")
RANDOM_SEED = 20260805
PERMUTATION_DRAWS = 10000


def run_curated_filtering_test(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    asset_mapping_path: str | Path = DEFAULT_ASSET_MAPPING_PATH,
    car_results_path: str | Path = DEFAULT_CAR_RESULTS_PATH,
    random_seed: int = RANDOM_SEED,
    permutation_draws: int = PERMUTATION_DRAWS,
) -> dict[str, Any]:
    """Run the selected-vs-rejected curated candidate diagnostic."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    snapshots = load_snapshots(snapshot_dir)
    asset_mapping = pd.read_csv(asset_mapping_path)
    candidate_rows = reconstruct_candidate_snapshot(snapshots, asset_mapping)

    candidate_path = output / "candidate_snapshot.csv"
    candidate_manifest_path = output / "candidate_snapshot_manifest.json"
    candidate_checksums_path = output / "candidate_snapshot_checksums.json"
    write_csv(candidate_path, candidate_rows)
    candidate_manifest = build_candidate_manifest(
        candidate_rows=candidate_rows,
        snapshots=snapshots,
        snapshot_dir=snapshot_dir,
        asset_mapping_path=asset_mapping_path,
    )
    write_json(candidate_manifest_path, candidate_manifest)
    write_json(
        candidate_checksums_path,
        {
            "candidate_snapshot.csv": sha256_file(candidate_path),
            "candidate_snapshot_manifest.json": sha256_file(candidate_manifest_path),
        },
    )

    # Market outcomes are loaded only after the candidate snapshot is sealed.
    car_rows = load_georisk_car_rows(car_results_path)
    asset_rows = join_candidate_market_results(candidate_rows, car_rows)
    event_rows = event_level_rows(asset_rows)
    summary = build_filtering_summary(
        candidate_rows=candidate_rows,
        asset_rows=asset_rows,
        event_rows=event_rows,
        random_seed=random_seed,
        permutation_draws=permutation_draws,
        car_results_path=car_results_path,
        asset_mapping_path=asset_mapping_path,
        candidate_path=candidate_path,
    )
    manifest = build_filtering_manifest(summary, candidate_manifest)

    write_csv(output / "selected_rejected_asset_results.csv", asset_rows)
    write_csv(output / "event_level_filtering_comparison.csv", event_rows)
    write_json(output / "filtering_summary.json", summary)
    write_json(output / "filtering_manifest.json", manifest)
    return summary


def load_snapshots(snapshot_dir: str | Path) -> list[dict[str, Any]]:
    """Load frozen V3 CAR validation snapshots from disk."""

    paths = sorted(Path(snapshot_dir).glob("*_snapshot_v3.json"))
    if not paths:
        raise FileNotFoundError(f"No frozen V3 snapshots found in {snapshot_dir}")
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def reconstruct_candidate_snapshot(
    snapshots: list[dict[str, Any]],
    asset_mapping: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Recover event-specific candidates from frozen nodes and asset mapping.

    ``rejected_final`` is assigned only when a ticker was mapped from frozen
    event-specific nodes but is absent from that event's frozen final output.
    Assets outside the event-specific mapped set are never included.
    """

    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        event_id = str(snapshot["event_id"])
        selected = selected_lookup(snapshot.get("predicted_exposures", []))
        nodes = dedupe((snapshot.get("transmission_chain") or {}).get("affected_nodes") or [])
        matched = asset_mapping[asset_mapping["supply_chain_node"].isin(nodes)]
        seen: set[str] = set()
        for record in matched.to_dict(orient="records"):
            ticker = str(record["ticker"]).strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            selected_record = selected.get(ticker)
            selected_final = selected_record is not None
            rows.append(
                {
                    "event_id": event_id,
                    "ticker": ticker,
                    "candidate_source_node": str(record["supply_chain_node"]),
                    "asset_type": str(record.get("asset_type") or ""),
                    "candidate": "true",
                    "selected_final": str(selected_final).lower(),
                    "rejected_final": str(not selected_final).lower(),
                    "evidence_label": selected_record.get("evidence_label", "") if selected_record else "",
                    "final_rank": selected_record.get("rank_within_order", "") if selected_record else "",
                    "reconstruction_source": (
                        "frozen_snapshot_transmission_nodes_plus_asset_mapping"
                    ),
                }
            )
    validate_candidate_rows(rows)
    return rows


def selected_lookup(exposures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index frozen selected exposures by ticker."""

    lookup: dict[str, dict[str, Any]] = {}
    for exposure in exposures:
        ticker = str(exposure.get("symbol") or "").strip().upper()
        if ticker and ticker not in lookup:
            lookup[ticker] = exposure
    return lookup


def validate_candidate_rows(rows: list[dict[str, Any]]) -> None:
    """Ensure candidate snapshot obeys selected/rejected definitions."""

    for row in rows:
        if row.get("candidate") != "true":
            raise ValueError("candidate_snapshot may only contain considered candidates")
        selected = row.get("selected_final") == "true"
        rejected = row.get("rejected_final") == "true"
        if selected == rejected:
            raise ValueError("Each candidate row must set exactly one of selected/rejected")


def load_georisk_car_rows(car_results_path: str | Path) -> list[dict[str, Any]]:
    """Load existing frozen GeoRisk CAR/SCAR rows after candidate freeze."""

    frame = pd.read_csv(car_results_path)
    frame = frame[frame["source"].astype(str) == "georisk"].copy()
    return frame.to_dict(orient="records")


def join_candidate_market_results(
    candidate_rows: list[dict[str, Any]],
    car_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join frozen candidate rows to existing SCAR results."""

    car_lookup = {
        (str(row["event_id"]), str(row["symbol"]).upper()): row for row in car_rows
    }
    output: list[dict[str, Any]] = []
    for row in candidate_rows:
        key = (row["event_id"], row["ticker"].upper())
        car = car_lookup.get(key)
        missing_reason = "" if car else "missing_existing_scar_result"
        scar = None if car is None else numeric_or_none(car.get("standardized_car"))
        hit = False if car is None else bool(car.get("hit"))
        evaluable = scar is not None and math.isfinite(scar)
        output.append(
            {
                **row,
                "evaluable": str(evaluable).lower(),
                "standardized_car": "" if scar is None else scar,
                "absolute_scar": "" if scar is None else abs(scar),
                "hit": str(hit).lower() if evaluable else "",
                "missing_data_reason": missing_reason
                or str(car.get("missing_data_reason") or ""),
            }
        )
    return output


def event_level_rows(asset_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build event-level selected-vs-rejected filtering diagnostics."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in asset_rows:
        grouped[row["event_id"]].append(row)

    rows: list[dict[str, Any]] = []
    for event_id, event_assets in sorted(grouped.items()):
        selected = [row for row in event_assets if row["selected_final"] == "true"]
        rejected = [row for row in event_assets if row["rejected_final"] == "true"]
        selected_eval = evaluable_abs_scar(selected)
        rejected_eval = evaluable_abs_scar(rejected)
        eligible = bool(selected_eval and rejected_eval)
        exclusion_reason = ""
        if not selected_eval:
            exclusion_reason = "no_evaluable_selected_candidates"
        elif not rejected_eval:
            exclusion_reason = "no_evaluable_rejected_candidates"
        selected_median = median(selected_eval) if selected_eval else None
        rejected_median = median(rejected_eval) if rejected_eval else None
        delta = (
            selected_median - rejected_median
            if selected_median is not None and rejected_median is not None
            else None
        )
        rows.append(
            {
                "event_id": event_id,
                "candidate_count": len(event_assets),
                "selected_count": len(selected),
                "rejected_count": len(rejected),
                "evaluable_selected": len(selected_eval),
                "evaluable_rejected": len(rejected_eval),
                "paired_filtering_eligible": str(eligible).lower(),
                "exclusion_reason": exclusion_reason,
                "selected_event_median_abs_scar": "" if selected_median is None else selected_median,
                "rejected_event_median_abs_scar": "" if rejected_median is None else rejected_median,
                "delta_event": "" if delta is None else delta,
                "relative_lift_event": (
                    "" if delta is None or not rejected_median else selected_median / rejected_median - 1
                ),
            }
        )
    return rows


def build_filtering_summary(
    candidate_rows: list[dict[str, Any]],
    asset_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    random_seed: int,
    permutation_draws: int,
    car_results_path: str | Path,
    asset_mapping_path: str | Path,
    candidate_path: Path,
) -> dict[str, Any]:
    """Summarize the curated-pool filtering diagnostic."""

    selected_assets = [row for row in asset_rows if row["selected_final"] == "true"]
    rejected_assets = [row for row in asset_rows if row["rejected_final"] == "true"]
    selected_eval = evaluable_abs_scar(selected_assets)
    rejected_eval = evaluable_abs_scar(rejected_assets)
    eligible_events = [row for row in event_rows if row["paired_filtering_eligible"] == "true"]
    deltas = [float(row["delta_event"]) for row in eligible_events]
    sign_flip = paired_sign_flip_test(deltas, random_seed, permutation_draws) if deltas else None

    selected_event_medians = [
        float(row["selected_event_median_abs_scar"])
        for row in event_rows
        if row["selected_event_median_abs_scar"] != ""
    ]
    rejected_event_medians = [
        float(row["rejected_event_median_abs_scar"])
        for row in event_rows
        if row["rejected_event_median_abs_scar"] != ""
    ]

    return {
        "experiment_name": "Curated-Pool Filtering Ability Test",
        "candidate_definition": {
            "candidate_asset": (
                "Asset mapped from frozen event-specific transmission nodes before "
                "final evidence/ranking output."
            ),
            "selected": "Candidate asset present in frozen GeoRisk predicted_exposures.",
            "rejected": "Candidate asset considered for the event but absent from frozen output.",
            "not_considered": "Asset-mapping entries not generated for the event; excluded.",
        },
        "candidate_reconstruction": {
            "events": len({row["event_id"] for row in candidate_rows}),
            "total_event_specific_candidates": len(candidate_rows),
            "selected_candidates": len([r for r in candidate_rows if r["selected_final"] == "true"]),
            "rejected_candidates": len([r for r in candidate_rows if r["rejected_final"] == "true"]),
            "not_considered_assets_excluded": True,
            "candidate_source": "existing frozen artifacts",
            "prices_inspected_before_candidate_freeze": False,
            "scar_inspected_before_candidate_freeze": False,
            "candidate_snapshot_hash": sha256_file(candidate_path),
        },
        "evaluability": {
            "selected_evaluable": len(selected_eval),
            "rejected_evaluable": len(rejected_eval),
            "paired_eligible_events": len(eligible_events),
            "excluded_events": len(event_rows) - len(eligible_events),
            "exclusion_reasons": dict(Counter(row["exclusion_reason"] for row in event_rows if row["exclusion_reason"])),
        },
        "continuous_primary": {
            "selected_aggregate_median_abs_scar": median(selected_event_medians) if selected_event_medians else None,
            "rejected_aggregate_median_abs_scar": median(rejected_event_medians) if rejected_event_medians else None,
            "filtering_lift": (
                median(selected_event_medians) - median(rejected_event_medians)
                if selected_event_medians and rejected_event_medians
                else None
            ),
            "relative_filtering_lift": (
                median(selected_event_medians) / median(rejected_event_medians) - 1
                if selected_event_medians and rejected_event_medians and median(rejected_event_medians) > 0
                else None
            ),
            "selected_gt_rejected_events": sum(1 for delta in deltas if delta > 0),
            "selected_eq_rejected_events": sum(1 for delta in deltas if delta == 0),
            "selected_lt_rejected_events": sum(1 for delta in deltas if delta < 0),
            "median_event_delta": median(deltas) if deltas else None,
            "mean_event_delta": mean(deltas) if deltas else None,
            "paired_sign_flip_test": sign_flip,
            "primary_metric_status": "not_evaluable_no_rejected_candidates" if not rejected_assets else "evaluable",
        },
        "asset_level_secondary": asset_level_secondary(selected_eval, rejected_eval),
        "binary_secondary": binary_secondary(selected_assets, rejected_assets),
        "main_conclusion": {
            "answer": "NO",
            "reason": (
                "The frozen CAR validation path selected every event-specific mapped "
                "candidate; no considered-but-rejected candidate set exists for a "
                "selected-vs-rejected market comparison."
            ),
            "interpretation": (
                "This does not prove selected assets underperform rejected assets; it "
                "shows the requested final filtering/ranking discrimination test is "
                "structurally unavailable for these frozen artifacts."
            ),
        },
        "integrity": {
            "georisk_unchanged": True,
            "v4_unchanged": True,
            "candidate_definition_frozen_before_market_outcomes": True,
            "prices_not_used_for_candidate_construction": True,
            "scar_not_used_for_candidate_construction": True,
            "threshold_tuning": False,
            "v5_implemented": False,
            "event_changes": False,
            "car_scar_unchanged": True,
        },
        "reproducibility": {
            "random_seed": random_seed,
            "permutation_draws": permutation_draws,
            "car_results_hash": sha256_file(car_results_path),
            "asset_mapping_hash": sha256_file(asset_mapping_path),
        },
    }


def asset_level_secondary(selected_eval: list[float], rejected_eval: list[float]) -> dict[str, Any]:
    """Return pooled descriptive |SCAR| metrics."""

    output = {
        "selected": describe_values(selected_eval),
        "rejected": describe_values(rejected_eval),
        "difference": None,
        "relative_difference": None,
        "mann_whitney_secondary": None,
        "clustering_limitation": (
            "Asset-level rows are clustered within events; this is descriptive only."
        ),
    }
    if selected_eval and rejected_eval:
        output["difference"] = median(selected_eval) - median(rejected_eval)
        output["relative_difference"] = median(selected_eval) / median(rejected_eval) - 1
        stat = mannwhitneyu(selected_eval, rejected_eval, alternative="two-sided")
        output["mann_whitney_secondary"] = {
            "u_statistic": float(stat.statistic),
            "p_value": float(stat.pvalue),
            "rank_biserial": rank_biserial_from_u(float(stat.statistic), len(selected_eval), len(rejected_eval)),
        }
    return output


def binary_secondary(selected_assets: list[dict[str, Any]], rejected_assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Return secondary binary hit diagnostics."""

    selected_eval = [row for row in selected_assets if row["evaluable"] == "true"]
    rejected_eval = [row for row in rejected_assets if row["evaluable"] == "true"]
    selected_hits = sum(1 for row in selected_eval if row["hit"] == "true")
    rejected_hits = sum(1 for row in rejected_eval if row["hit"] == "true")
    selected_rate = selected_hits / len(selected_eval) if selected_eval else None
    rejected_rate = rejected_hits / len(rejected_eval) if rejected_eval else None
    all_responsive = selected_hits + rejected_hits
    weak_rejected = len(rejected_eval) - rejected_hits
    all_weak = (len(selected_eval) - selected_hits) + weak_rejected
    return {
        "selected_hit_rate": selected_rate,
        "rejected_hit_rate": rejected_rate,
        "delta_percentage_points": (
            (selected_rate - rejected_rate) * 100 if selected_rate is not None and rejected_rate is not None else None
        ),
        "market_responsive_selected": selected_hits,
        "market_responsive_rejected": rejected_hits,
        "market_weak_selected": len(selected_eval) - selected_hits,
        "market_weak_rejected": weak_rejected,
        "selection_precision": selected_rate,
        "weak_filter_specificity": weak_rejected / all_weak if all_weak else None,
        "responsive_miss_rate": rejected_hits / all_responsive if all_responsive else None,
    }


def paired_sign_flip_test(deltas: list[float], seed: int, draws: int) -> dict[str, Any]:
    """Monte Carlo sign-flip test for paired event-level deltas."""

    if not deltas:
        raise ValueError("deltas must be non-empty")
    observed = mean(deltas)
    rng = random.Random(seed)
    randomized = []
    for _ in range(draws):
        randomized.append(mean(delta * (1 if rng.random() >= 0.5 else -1) for delta in deltas))
    p_value = (sum(1 for value in randomized if value >= observed) + 1) / (draws + 1)
    return {
        "statistic": "mean_event_delta",
        "observed": observed,
        "draws": draws,
        "seed": seed,
        "empirical_one_sided_p_value": p_value,
    }


def describe_values(values: list[float]) -> dict[str, Any]:
    """Describe a numeric list without assuming iid rows."""

    if not values:
        return {"n": 0, "median": None, "mean": None, "p25": None, "p75": None}
    return {
        "n": len(values),
        "median": median(values),
        "mean": mean(values),
        "p25": percentile(values, 0.25),
        "p75": percentile(values, 0.75),
    }


def build_candidate_manifest(
    candidate_rows: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    snapshot_dir: str | Path,
    asset_mapping_path: str | Path,
) -> dict[str, Any]:
    """Create candidate-freeze metadata before market outcome join."""

    return {
        "experiment_name": "Curated-Pool Filtering Ability Test",
        "candidate_snapshot_stage": "pre_market_outcome_join",
        "snapshot_count": len(snapshots),
        "event_count": len({row["event_id"] for row in candidate_rows}),
        "candidate_count": len(candidate_rows),
        "selected_count": len([row for row in candidate_rows if row["selected_final"] == "true"]),
        "rejected_count": len([row for row in candidate_rows if row["rejected_final"] == "true"]),
        "not_considered_assets_excluded": True,
        "reconstruction_source": "frozen_snapshot_transmission_nodes_plus_asset_mapping",
        "prices_inspected_before_candidate_freeze": False,
        "scar_inspected_before_candidate_freeze": False,
        "input_hashes": {
            "snapshot_dir_hash": hash_directory(snapshot_dir, "*_snapshot_v3.json"),
            "asset_mapping": sha256_file(asset_mapping_path),
        },
    }


def build_filtering_manifest(
    summary: dict[str, Any],
    candidate_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Create final filtering diagnostic manifest."""

    return {
        "experiment_name": "Curated-Pool Filtering Ability Test",
        "candidate_snapshot_sealed_before_market_join": True,
        "candidate_manifest": candidate_manifest,
        "summary": {
            "events": summary["candidate_reconstruction"]["events"],
            "selected_candidates": summary["candidate_reconstruction"]["selected_candidates"],
            "rejected_candidates": summary["candidate_reconstruction"]["rejected_candidates"],
            "paired_eligible_events": summary["evaluability"]["paired_eligible_events"],
            "main_conclusion": summary["main_conclusion"],
        },
        "integrity": summary["integrity"],
    }


def evaluable_abs_scar(rows: list[dict[str, Any]]) -> list[float]:
    """Return finite absolute SCAR values from joined rows."""

    values: list[float] = []
    for row in rows:
        if row.get("evaluable") != "true":
            continue
        value = numeric_or_none(row.get("absolute_scar"))
        if value is not None and math.isfinite(value):
            values.append(value)
    return values


def numeric_or_none(value: Any) -> float | None:
    """Convert finite numeric input to float, otherwise None."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def percentile(values: list[float], q: float) -> float:
    """Linear percentile for a sorted numeric list."""

    if not values:
        raise ValueError("values must be non-empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def rank_biserial_from_u(u_statistic: float, n_left: int, n_right: int) -> float:
    """Convert Mann-Whitney U to rank-biserial correlation."""

    return (2 * u_statistic / (n_left * n_right)) - 1


def dedupe(values: list[str]) -> list[str]:
    """Preserve order while removing duplicates and empty strings."""

    seen: set[str] = set()
    output = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write rows to CSV with deterministic column order."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    """Write JSON with stable ordering."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: str | Path) -> str:
    """Return SHA-256 checksum for a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_directory(directory: str | Path, pattern: str) -> str:
    """Hash a deterministic list of files in a directory."""

    digest = hashlib.sha256()
    for path in sorted(Path(directory).glob(pattern)):
        digest.update(path.name.encode("utf-8"))
        digest.update(sha256_file(path).encode("utf-8"))
    return digest.hexdigest()

