"""Build and freeze a V3 held-out validation set for linkage-tier analysis.

This script is intentionally pre-CAR only. It does not read prices, CAR
outputs, standardized CAR, returns, hit labels, or baseline performance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

from src.pipeline import run_pipeline
from src.validation.car_calculator import MarketModelConfig
from src.validation.prediction_snapshot import (
    SNAPSHOT_NOTE,
    create_full_pipeline_prediction_snapshot,
    current_git_commit,
    predicted_exposure_from_evidence_result,
    validate_full_pipeline_snapshot,
)
from src.validation.validation_set_builder import (
    DEFAULT_KB_PATH,
    MIN_EVENT_TEXT_WORDS,
    candidate_event_id,
    candidate_text,
    construct_baseline_exposures,
    find_kb_overlap,
    has_sufficient_calendar_room,
    load_candidate_events,
    load_historical_cases,
    load_existing_manifest_events,
    normalize_text,
    sha256_file,
)


DEFAULT_V3_DIR = Path("data/validation_v3")
DEFAULT_V3_CANDIDATES = DEFAULT_V3_DIR / "candidate_events_raw.json"
DEFAULT_V2_MANIFEST = Path("data/validation_events.yaml")
DEFAULT_V1_V2_SNAPSHOT_DIR = Path("data/validation_snapshots")
DEFAULT_TARGET_EVENTS = 12
SNAPSHOT_VERSION_V3 = "v3_full_pipeline_linkage_ontology"
INCIDENT_OVERLAP_SCORE = 0.72


def build_v3_validation_set(
    candidate_path: str | Path = DEFAULT_V3_CANDIDATES,
    output_dir: str | Path = DEFAULT_V3_DIR,
    kb_path: str | Path = DEFAULT_KB_PATH,
    v2_manifest_path: str | Path = DEFAULT_V2_MANIFEST,
    prior_snapshot_dir: str | Path = DEFAULT_V1_V2_SNAPSHOT_DIR,
    target_events: int = DEFAULT_TARGET_EVENTS,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Screen, select, and freeze V3 validation snapshots without CAR data."""

    assert_no_market_outcome_inputs()
    output = Path(output_dir)
    snapshot_dir = output / "prediction_snapshots"
    manifest_path = output / "v3_manifest.json"
    if manifest_path.exists() and not rebuild:
        raise FileExistsError(
            f"V3 manifest already exists: {manifest_path}. Pass --rebuild to replace V3 artifacts."
        )
    if rebuild and snapshot_dir.exists():
        for stale_snapshot in snapshot_dir.glob("*_snapshot_v3.json"):
            stale_snapshot.unlink()

    candidates = load_candidate_events(candidate_path)
    kb_cases = load_historical_cases(kb_path)
    prior_events = load_prior_event_records(v2_manifest_path, prior_snapshot_dir)
    config = MarketModelConfig()

    screens: list[dict[str, Any]] = []
    for candidate in candidates:
        screens.append(screen_v3_candidate(candidate, kb_cases, prior_events, config))
    reject_duplicate_candidate_incidents(screens)

    eligible = [screen for screen in screens if screen["accepted"]]
    selected = select_v3_events(eligible, target_events)
    snapshot_failures: list[dict[str, str]] = []
    snapshots: list[dict[str, Any]] = []

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for screen in selected:
        event = screen["validation_event"]
        snapshot_path = snapshot_dir / f"{event['event_id']}_snapshot_v3.json"
        if snapshot_path.exists() and not rebuild:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        else:
            try:
                snapshot = create_v3_snapshot(event)
                validate_v3_snapshot(snapshot)
            except Exception as exc:
                screen["accepted"] = False
                screen["decision"] = "rejected"
                screen["rejection_reasons"].append(f"snapshot_failed:{type(exc).__name__}")
                snapshot_failures.append(
                    {"event_id": event["event_id"], "reason": f"{type(exc).__name__}: {exc}"}
                )
                continue
            snapshot_path.write_text(
                json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        screen["snapshot_path"] = str(snapshot_path)
        snapshots.append(snapshot)

    final_selected_ids = [snapshot["event_id"] for snapshot in snapshots]
    accepted_screens = [
        screen for screen in selected if screen["candidate_event_id"] in set(final_selected_ids)
    ]

    write_v3_artifacts(
        output,
        screens,
        accepted_screens,
        snapshots,
        kb_cases,
        kb_path,
        prior_events,
        config,
        target_events,
        snapshot_failures,
        manifest_path,
    )
    return {
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "accepted_count": len(accepted_screens),
        "event_ids": final_selected_ids,
        "snapshot_count": len(snapshots),
        "snapshot_failures": snapshot_failures,
        "output_dir": str(output),
    }


def screen_v3_candidate(
    candidate: dict[str, Any],
    kb_cases: list[dict[str, Any]],
    prior_events: list[dict[str, str]],
    config: MarketModelConfig,
) -> dict[str, Any]:
    """Apply objective V3 eligibility checks and pre-CAR pipeline coverage."""

    event_id = candidate_event_id(candidate)
    text = candidate_text(candidate)
    reasons: list[str] = []
    parsed_date = pd.to_datetime(candidate.get("event_date"), errors="coerce")
    if not event_id:
        reasons.append("missing_event_id")
    if pd.isna(parsed_date):
        reasons.append("invalid_or_ambiguous_event_date")
    elif not has_sufficient_calendar_room(pd.Timestamp(parsed_date), config):
        reasons.append("insufficient_historical_date_range_for_car")
    if len(text.split()) < MIN_EVENT_TEXT_WORDS:
        reasons.append("insufficient_contemporaneous_event_description")

    kb_overlap = find_kb_overlap(candidate, kb_cases)
    strict_kb_overlap = find_strict_kb_incident_overlap(candidate, kb_cases)
    if kb_overlap["incident_level_overlap"] or strict_kb_overlap["incident_level_overlap"]:
        reasons.append("same_incident_in_kb")

    prior_overlap = find_prior_overlap(candidate, prior_events)
    if prior_overlap["overlaps_prior"]:
        reasons.append("overlaps_v1_v2_event")

    prediction_summary: dict[str, Any] = empty_prediction_summary()
    validation_event: dict[str, Any] | None = None
    if not reasons:
        try:
            report = run_pipeline(text, event_analyzer="rule")
            exposures = [
                predicted_exposure_from_evidence_result(event_id, result).model_dump(mode="json")
                for result in report.evidence_results
            ]
            if not exposures:
                reasons.append("georisk_no_valid_mapped_exposure")
            elif duplicate_exposure_keys(exposures):
                reasons.append("duplicate_predicted_exposure_keys")
            else:
                prediction_summary = summarize_exposures(exposures)
                validation_event = {
                    "event_id": event_id,
                    "event_date": str(candidate.get("event_date")),
                    "headline": str(candidate.get("headline") or ""),
                    "event_description": text,
                    "event_type": candidate.get("event_type") or candidate.get("event_type_hint"),
                    "regions": candidate.get("regions") or candidate.get("regions_hint") or [],
                    "source": candidate.get("source"),
                    "source_url": candidate.get("source_url"),
                    "retrieval_query": candidate.get("retrieval_query"),
                    "supporting_sources": candidate.get("supporting_sources", []),
                    "held_out_from_kb": True,
                    "clear_t0": True,
                    "clean_estimation_window": True,
                    "status": "accepted",
                    "baseline_exposures": [
                        baseline.model_dump(mode="json") for baseline in construct_baseline_exposures()
                    ],
                }
        except Exception as exc:
            reasons.append(f"georisk_pipeline_failed:{type(exc).__name__}")

    return {
        "candidate_event_id": event_id,
        "candidate": candidate,
        "event_date": candidate.get("event_date"),
        "headline": candidate.get("headline"),
        "source": candidate.get("source"),
        "source_url": candidate.get("source_url"),
        "event_type": candidate.get("event_type") or candidate.get("event_type_hint"),
        "regions": candidate.get("regions") or candidate.get("regions_hint") or [],
        "description": text,
        "likely_first_order_nodes": candidate.get("likely_first_order_nodes", []),
        "plausible_second_order_mechanisms": candidate.get("plausible_second_order_mechanisms", []),
        "exact_event_exists_in_kb": kb_overlap["incident_level_overlap"],
        "overlaps_v1_v2": prior_overlap["overlaps_prior"],
        "date_sufficiently_precise": not pd.isna(parsed_date),
        "suitable_for_car": not any(
            reason
            in {
                "invalid_or_ambiguous_event_date",
                "insufficient_historical_date_range_for_car",
                "insufficient_contemporaneous_event_description",
            }
            for reason in reasons
        ),
        "accepted": not reasons,
        "decision": "accepted" if not reasons else "rejected",
        "rejection_reasons": reasons,
        "kb_overlap_report": kb_overlap,
        "strict_kb_overlap_report": strict_kb_overlap,
        "prior_overlap_report": prior_overlap,
        "prediction_summary": prediction_summary,
        "validation_event": validation_event,
    }


def create_v3_snapshot(event: dict[str, Any]) -> dict[str, Any]:
    """Create one V3 full-pipeline snapshot from frozen event text."""

    report = run_pipeline(event["event_description"], event_analyzer="rule")
    exposures = [
        predicted_exposure_from_evidence_result(event["event_id"], result).model_dump(mode="json")
        for result in report.evidence_results
    ]
    snapshot = {
        "event_id": event["event_id"],
        "event_date": event["event_date"],
        "headline": event["headline"],
        "event_description": event["event_description"],
        "event_type": event["event_type"],
        "regions": event["regions"],
        "source": event["source"],
        "source_url": event["source_url"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "predicted_exposures": exposures,
        "baseline_exposures": event["baseline_exposures"],
        "retrieved_case_ids": [case.case_id for case in report.retrieved_cases],
        "transmission_chain": report.transmission_chain.model_dump(mode="json"),
        "pipeline_mode": "full_georisk_pipeline",
        "event_analyzer_mode": "rule",
        "retrieval_configuration": {"top_k": 3},
        "snapshot_version": SNAPSHOT_VERSION_V3,
        "git_commit": current_git_commit(),
        "note": SNAPSHOT_NOTE,
    }
    validate_full_pipeline_snapshot(snapshot, report)
    return snapshot


def validate_v3_snapshot(snapshot: dict[str, Any]) -> None:
    """Validate V3 snapshot integrity before freezing."""

    exposures = snapshot.get("predicted_exposures", [])
    if snapshot.get("snapshot_version") != SNAPSHOT_VERSION_V3:
        raise RuntimeError("v3_snapshot_integrity_failed:wrong_snapshot_version")
    if snapshot.get("pipeline_mode") != "full_georisk_pipeline":
        raise RuntimeError("v3_snapshot_integrity_failed:not_full_pipeline")
    if duplicate_exposure_keys(exposures):
        raise RuntimeError("v3_snapshot_integrity_failed:duplicate_event_symbol_node")
    for exposure in exposures:
        if not exposure.get("linkage_tier"):
            raise RuntimeError("v3_snapshot_integrity_failed:missing_linkage_tier")
        if not exposure.get("linkage_rationale"):
            raise RuntimeError("v3_snapshot_integrity_failed:missing_linkage_rationale")
        if exposure.get("transmission_order") == "second_order" and exposure.get("transmission_order") != "second_order":
            raise RuntimeError("v3_snapshot_integrity_failed:second_order_not_preserved")


def select_v3_events(screens: list[dict[str, Any]], target_events: int) -> list[dict[str, Any]]:
    """Select V3 events deterministically, preferring second-order coverage."""

    ordered = sorted(
        screens,
        key=lambda screen: (
            str(screen["event_type"]),
            -int(screen["prediction_summary"]["second_order_count"] > 0),
            str(screen["event_date"]),
            str(screen["candidate_event_id"]),
        ),
    )
    selected: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for screen in ordered:
        if screen["prediction_summary"]["second_order_count"] <= 0:
            continue
        event_type = str(screen["event_type"])
        if event_type in seen_types:
            continue
        selected.append(screen)
        seen_types.add(event_type)
        if len(selected) >= target_events:
            return selected

    for screen in ordered:
        if screen in selected or screen["prediction_summary"]["second_order_count"] <= 0:
            continue
        selected.append(screen)
        if len(selected) >= target_events:
            return selected

    for screen in ordered:
        if screen in selected:
            continue
        selected.append(screen)
        if len(selected) >= target_events:
            return selected
    return selected


def reject_duplicate_candidate_incidents(screens: list[dict[str, Any]]) -> None:
    """Reject duplicate candidate records that describe the same incident."""

    kept: list[dict[str, Any]] = []
    for screen in sorted(
        screens,
        key=lambda item: (
            str(item["event_type"]),
            str(item["event_date"]),
            str(item["headline"]),
            str(item["candidate_event_id"]),
        ),
    ):
        if not screen["accepted"]:
            continue
        duplicate_of = next((kept_screen for kept_screen in kept if same_candidate_incident(screen, kept_screen)), None)
        if duplicate_of is None:
            kept.append(screen)
            continue
        screen["accepted"] = False
        screen["decision"] = "rejected"
        screen["rejection_reasons"].append(
            f"duplicate_of_candidate:{duplicate_of['candidate_event_id']}"
        )


def same_candidate_incident(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Return whether two accepted candidates are likely duplicate incidents."""

    left_date = pd.to_datetime(left.get("event_date"), errors="coerce")
    right_date = pd.to_datetime(right.get("event_date"), errors="coerce")
    if pd.isna(left_date) or pd.isna(right_date):
        return False
    days_apart = abs((pd.Timestamp(left_date) - pd.Timestamp(right_date)).days)
    if days_apart > 3:
        return False
    headline_score = SequenceMatcher(
        None,
        normalize_text(str(left.get("headline") or "")),
        normalize_text(str(right.get("headline") or "")),
    ).ratio()
    token_score = token_jaccard(str(left.get("description") or ""), str(right.get("description") or ""))
    entity_overlap = set(left.get("candidate", {}).get("entities", [])) & set(
        right.get("candidate", {}).get("entities", [])
    )
    same_source = bool(left.get("source_url")) and left.get("source_url") == right.get("source_url")
    same_type = str(left["event_type"]) == str(right["event_type"])
    return (
        (same_source and days_apart <= 1)
        or headline_score >= 0.55
        or (same_type and headline_score >= 0.25 and bool(entity_overlap))
        or (days_apart <= 1 and token_score >= 0.45)
    )


def find_strict_kb_incident_overlap(
    candidate: dict[str, Any],
    kb_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Catch exact KB incidents missed by broad fuzzy scoring."""

    candidate_date = pd.to_datetime(candidate.get("event_date"), errors="coerce")
    closest: list[dict[str, Any]] = []
    incident_level_overlap = False
    for case in kb_cases:
        case_date = pd.to_datetime(case.get("date"), errors="coerce")
        if pd.isna(candidate_date) or pd.isna(case_date):
            days_apart = None
            date_close = False
        else:
            days_apart = abs((pd.Timestamp(candidate_date) - pd.Timestamp(case_date)).days)
            date_close = days_apart <= 3
        text_score = token_jaccard(candidate_text(candidate), " ".join([
            str(case.get("event_name") or ""),
            str(case.get("summary") or ""),
            str(case.get("retrieval_text") or ""),
        ]))
        name_score = SequenceMatcher(
            None,
            normalize_text(str(candidate.get("headline") or "")),
            normalize_text(str(case.get("event_name") or "")),
        ).ratio()
        score = round((0.60 if date_close else 0.0) + 0.25 * text_score + 0.15 * name_score, 4)
        if date_close and (text_score >= 0.15 or name_score >= 0.30):
            incident_level_overlap = True
        closest.append(
            {
                "case_id": case.get("event_id"),
                "case_name": case.get("event_name"),
                "case_date": case.get("date"),
                "days_apart": days_apart,
                "token_overlap": round(text_score, 4),
                "name_similarity": round(name_score, 4),
                "score": score,
            }
        )
    closest.sort(key=lambda item: item["score"], reverse=True)
    return {
        "incident_level_overlap": incident_level_overlap,
        "closest_cases": closest[:3],
    }


def token_jaccard(left: str, right: str) -> float:
    """Return token overlap after dropping very common words."""

    stop = {
        "the", "and", "for", "with", "from", "that", "this", "into", "after",
        "against", "under", "through", "while", "including", "announced",
        "source", "keywords", "global", "united", "states",
    }
    left_tokens = {token for token in normalize_text(left).split() if len(token) > 2 and token not in stop}
    right_tokens = {token for token in normalize_text(right).split() if len(token) > 2 and token not in stop}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def summarize_exposures(exposures: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize pre-CAR prediction coverage."""

    first_order = [e for e in exposures if e.get("transmission_order") == "first_order"]
    second_order = [e for e in exposures if e.get("transmission_order") == "second_order"]
    return {
        "total_exposures": len(exposures),
        "first_order_count": len(first_order),
        "second_order_count": len(second_order),
        "evidence_distribution": dict(Counter(e.get("evidence_label") or "unknown" for e in exposures)),
        "linkage_distribution": dict(Counter(e.get("linkage_tier") or "unknown" for e in exposures)),
        "second_order_linkage_distribution": dict(Counter(e.get("linkage_tier") or "unknown" for e in second_order)),
        "second_order_evidence_distribution": dict(Counter(e.get("evidence_label") or "unknown" for e in second_order)),
    }


def empty_prediction_summary() -> dict[str, Any]:
    """Return an empty prediction coverage summary."""

    return {
        "total_exposures": 0,
        "first_order_count": 0,
        "second_order_count": 0,
        "evidence_distribution": {},
        "linkage_distribution": {},
        "second_order_linkage_distribution": {},
        "second_order_evidence_distribution": {},
    }


def duplicate_exposure_keys(exposures: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return duplicate event-symbol-node keys."""

    keys = Counter(
        (str(e.get("event_id")), str(e.get("symbol")), str(e.get("node")))
        for e in exposures
    )
    return [key for key, count in keys.items() if count > 1]


def load_prior_event_records(
    v2_manifest_path: str | Path,
    prior_snapshot_dir: str | Path,
) -> list[dict[str, str]]:
    """Load V1/V2 event IDs and text for overlap exclusion."""

    records: dict[str, dict[str, str]] = {}
    path = Path(v2_manifest_path)
    if path.exists():
        for event in load_existing_manifest_events(path):
            records[event.event_id] = {
                "event_id": event.event_id,
                "event_date": event.event_date,
                "text": event.event_description,
                "source": str(path),
            }
    for snapshot_path in Path(prior_snapshot_dir).glob("*_snapshot*.json"):
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        event_id = str(payload.get("event_id") or snapshot_path.stem.replace("_snapshot_v2", "").replace("_snapshot", ""))
        records.setdefault(
            event_id,
            {
                "event_id": event_id,
                "event_date": str(payload.get("event_date") or ""),
                "text": str(payload.get("event_description") or payload.get("headline") or ""),
                "source": str(snapshot_path),
            },
        )
    return sorted(records.values(), key=lambda item: item["event_id"])


def find_prior_overlap(candidate: dict[str, Any], prior_events: list[dict[str, str]]) -> dict[str, Any]:
    """Find exact or near incident overlap with prior V1/V2 validation events."""

    event_id = candidate_event_id(candidate)
    candidate_date = pd.to_datetime(candidate.get("event_date"), errors="coerce")
    candidate_norm = normalize_text(candidate_text(candidate))
    closest: list[dict[str, Any]] = []
    overlaps = False
    for prior in prior_events:
        prior_date = pd.to_datetime(prior.get("event_date"), errors="coerce")
        days_apart = None
        date_score = 0.0
        if not pd.isna(candidate_date) and not pd.isna(prior_date):
            days_apart = abs((pd.Timestamp(candidate_date) - pd.Timestamp(prior_date)).days)
            date_score = 1.0 if days_apart <= 3 else 0.5 if days_apart <= 14 else 0.0
        text_score = SequenceMatcher(None, candidate_norm, normalize_text(prior.get("text") or "")).ratio()
        id_match = event_id == prior.get("event_id")
        score = 1.0 if id_match else round(0.55 * text_score + 0.45 * date_score, 4)
        if id_match or score >= INCIDENT_OVERLAP_SCORE:
            overlaps = True
        closest.append(
            {
                "event_id": prior.get("event_id"),
                "event_date": prior.get("event_date"),
                "source": prior.get("source"),
                "score": score,
                "days_apart": days_apart,
                "text_similarity": round(text_score, 4),
                "id_match": id_match,
            }
        )
    closest.sort(key=lambda item: item["score"], reverse=True)
    return {"overlaps_prior": overlaps, "closest_prior_events": closest[:3]}


def write_v3_artifacts(
    output: Path,
    screens: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    kb_cases: list[dict[str, Any]],
    kb_path: str | Path,
    prior_events: list[dict[str, str]],
    config: MarketModelConfig,
    target_events: int,
    snapshot_failures: list[dict[str, str]],
    manifest_path: Path,
) -> None:
    """Write V3 manifest, audit CSVs, summary JSON, and design report."""

    output.mkdir(parents=True, exist_ok=True)
    write_screen_csv(output / "candidate_events.csv", screens, include_accepted=True)
    write_screen_csv(output / "excluded_events.csv", [s for s in screens if not s["accepted"]], include_accepted=False)
    write_screen_csv(output / "accepted_events.csv", selected, include_accepted=True)

    manifest = {
        "experiment_version": "V3",
        "research_question": "Among second-order GeoRisk exposures, do stronger ex-ante node-to-asset linkage tiers show stronger market reactions?",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": current_git_commit(),
        "candidate_source": "GDELT DOC 2.0 cached/public source records",
        "selection_rules": {
            "target_events": target_events,
            "ordering": "event_type, second_order_presence, event_date, event_id; first pass one event per type with second-order coverage, then fill deterministically",
            "outcome_data_used": False,
            "excluded_prior_v1_v2_events": True,
            "excluded_exact_kb_incidents": True,
        },
        "car_methodology_to_use_later": {
            "benchmark": "SPY",
            "estimation_window": [config.estimation_window_start, config.estimation_window_end],
            "event_window": [config.event_window_start, config.event_window_end],
            "significance_rule": "abs(standardized_car) >= 1.96",
            "market_model": "asset_return = alpha + beta * benchmark_return",
        },
        "event_ids": [snapshot["event_id"] for snapshot in snapshots],
        "events": [screen["validation_event"] for screen in selected],
        "snapshot_paths": [str(output / "prediction_snapshots" / f"{snapshot['event_id']}_snapshot_v3.json") for snapshot in snapshots],
        "manifest_hash": None,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest_hash"] = sha256_file(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = summarize_v3(screens, selected, snapshots, kb_cases, kb_path, prior_events, snapshot_failures, manifest)
    (output / "v3_snapshot_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_design_report(output / "v3_design_report.md", summary)


def write_screen_csv(path: Path, screens: list[dict[str, Any]], include_accepted: bool) -> None:
    """Write V3 candidate screening rows."""

    fields = [
        "candidate_event_id",
        "event_date",
        "headline",
        "source",
        "source_url",
        "event_type",
        "regions",
        "likely_first_order_nodes",
        "plausible_second_order_mechanisms",
        "exact_event_exists_in_kb",
        "overlaps_v1_v2",
        "date_sufficiently_precise",
        "suitable_for_car",
        "decision",
        "exclusion_reason",
        "total_exposures",
        "first_order_count",
        "second_order_count",
        "second_order_direct",
        "second_order_related",
        "second_order_broad_proxy",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for screen in screens:
            summary = screen["prediction_summary"]
            second_linkage = summary["second_order_linkage_distribution"]
            writer.writerow(
                {
                    "candidate_event_id": screen["candidate_event_id"],
                    "event_date": screen["event_date"],
                    "headline": screen["headline"],
                    "source": screen["source"],
                    "source_url": screen["source_url"],
                    "event_type": screen["event_type"],
                    "regions": ";".join(map(str, screen["regions"])),
                    "likely_first_order_nodes": ";".join(map(str, screen["likely_first_order_nodes"])),
                    "plausible_second_order_mechanisms": ";".join(map(str, screen["plausible_second_order_mechanisms"])),
                    "exact_event_exists_in_kb": screen["exact_event_exists_in_kb"],
                    "overlaps_v1_v2": screen["overlaps_v1_v2"],
                    "date_sufficiently_precise": screen["date_sufficiently_precise"],
                    "suitable_for_car": screen["suitable_for_car"],
                    "decision": screen["decision"] if include_accepted else "rejected",
                    "exclusion_reason": ";".join(screen["rejection_reasons"]),
                    "total_exposures": summary["total_exposures"],
                    "first_order_count": summary["first_order_count"],
                    "second_order_count": summary["second_order_count"],
                    "second_order_direct": second_linkage.get("direct_exposure", 0),
                    "second_order_related": second_linkage.get("related_exposure", 0),
                    "second_order_broad_proxy": second_linkage.get("broad_proxy", 0),
                }
            )


def summarize_v3(
    screens: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    kb_cases: list[dict[str, Any]],
    kb_path: str | Path,
    prior_events: list[dict[str, str]],
    snapshot_failures: list[dict[str, str]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return aggregate V3 pre-CAR coverage summary."""

    exposures = [exposure for snapshot in snapshots for exposure in snapshot.get("predicted_exposures", [])]
    second_order = [e for e in exposures if e.get("transmission_order") == "second_order"]
    first_order = [e for e in exposures if e.get("transmission_order") == "first_order"]
    linkage_x_evidence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for exposure in second_order:
        linkage_x_evidence[exposure.get("linkage_tier") or "unknown"][exposure.get("evidence_label") or "unknown"] += 1
    rejection_counts = Counter(reason for screen in screens for reason in screen["rejection_reasons"])
    event_level = []
    for snapshot in snapshots:
        second = [e for e in snapshot.get("predicted_exposures", []) if e.get("transmission_order") == "second_order"]
        counts = Counter(e.get("linkage_tier") or "unknown" for e in second)
        event_level.append(
            {
                "event_id": snapshot["event_id"],
                "event_date": snapshot["event_date"],
                "headline": snapshot.get("headline", ""),
                "second_order_total": len(second),
                "direct_exposure": counts.get("direct_exposure", 0),
                "related_exposure": counts.get("related_exposure", 0),
                "broad_proxy": counts.get("broad_proxy", 0),
            }
        )
    return {
        "candidate_count": len(screens),
        "accepted_events": len(snapshots),
        "rejected_events": len([screen for screen in screens if not screen["accepted"]]),
        "rejection_reason_counts": dict(rejection_counts),
        "final_event_ids": [snapshot["event_id"] for snapshot in snapshots],
        "prior_event_count": len(prior_events),
        "prior_overlap_in_final_event_ids": sorted(
            set(snapshot["event_id"] for snapshot in snapshots) & set(event["event_id"] for event in prior_events)
        ),
        "kb_case_count": len(kb_cases),
        "kb_hash": sha256_file(kb_path),
        "exact_kb_leakage_in_final": [
            screen["candidate_event_id"]
            for screen in selected
            if screen["exact_event_exists_in_kb"]
        ],
        "snapshot_count": len(snapshots),
        "snapshot_failures": snapshot_failures,
        "total_exposures": len(exposures),
        "first_order_exposures": len(first_order),
        "second_order_exposures": len(second_order),
        "second_order_linkage_distribution": dict(Counter(e.get("linkage_tier") or "unknown" for e in second_order)),
        "second_order_evidence_distribution": dict(Counter(e.get("evidence_label") or "unknown" for e in second_order)),
        "linkage_tier_x_evidence_level": {
            tier: dict(counts) for tier, counts in sorted(linkage_x_evidence.items())
        },
        "event_level_second_order_coverage": event_level,
        "manifest_hash": manifest["manifest_hash"],
        "car_methodology_to_use_later": manifest["car_methodology_to_use_later"],
        "outcome_data_used": False,
    }


def write_design_report(path: Path, summary: dict[str, Any]) -> None:
    """Write the human-readable V3 pre-CAR design report."""

    lines = [
        "# V3 Pre-CAR Validation Design Report",
        "",
        "This report covers event selection and prediction freezing only. It does not inspect prices, returns, CAR, standardized CAR, hit labels, or baseline performance.",
        "",
        "## Event-Set Summary",
        "",
        f"- Candidate events collected: {summary['candidate_count']}",
        f"- Accepted events: {summary['accepted_events']}",
        f"- Rejected events: {summary['rejected_events']}",
        f"- Snapshot failures: {len(summary['snapshot_failures'])}",
        f"- KB cases screened: {summary['kb_case_count']}",
        f"- V1/V2 overlap in final event IDs: {summary['prior_overlap_in_final_event_ids'] or 'none'}",
        f"- Exact KB leakage in final events: {summary['exact_kb_leakage_in_final'] or 'none'}",
        "",
        "## Rejection Reasons",
        "",
        "| reason | count |",
        "| --- | ---: |",
    ]
    for reason, count in sorted(summary["rejection_reason_counts"].items()):
        lines.append(f"| {reason} | {count} |")
    if not summary["rejection_reason_counts"]:
        lines.append("| none | 0 |")

    lines.extend(
        [
            "",
            "## Prediction Coverage",
            "",
            f"- Total exposures: {summary['total_exposures']}",
            f"- First-order exposures: {summary['first_order_exposures']}",
            f"- Second-order exposures: {summary['second_order_exposures']}",
            "",
            "## Second-Order Linkage Distribution",
            "",
            "| linkage_tier | count |",
            "| --- | ---: |",
        ]
    )
    for tier in ["direct_exposure", "related_exposure", "broad_proxy"]:
        lines.append(f"| {tier} | {summary['second_order_linkage_distribution'].get(tier, 0)} |")

    lines.extend(["", "## Second-Order Evidence Distribution", "", "| evidence_level | count |", "| --- | ---: |"])
    for level in ["historical_supported", "sector_proxy", "inference_only"]:
        lines.append(f"| {level} | {summary['second_order_evidence_distribution'].get(level, 0)} |")

    lines.extend(["", "## Linkage Tier x Evidence Level", "", "| linkage_tier | historical_supported | sector_proxy | inference_only |", "| --- | ---: | ---: | ---: |"])
    for tier in ["direct_exposure", "related_exposure", "broad_proxy"]:
        row = summary["linkage_tier_x_evidence_level"].get(tier, {})
        lines.append(
            f"| {tier} | {row.get('historical_supported', 0)} | {row.get('sector_proxy', 0)} | {row.get('inference_only', 0)} |"
        )

    lines.extend(["", "## Event-Level Coverage", "", "| event_id | second_order total | direct | related | broad_proxy |", "| --- | ---: | ---: | ---: | ---: |"])
    for event in summary["event_level_second_order_coverage"]:
        lines.append(
            f"| {event['event_id']} | {event['second_order_total']} | {event['direct_exposure']} | {event['related_exposure']} | {event['broad_proxy']} |"
        )

    lines.extend(
        [
            "",
            "## Frozen CAR Methodology",
            "",
            "- Benchmark: SPY",
            "- Estimation window: [-130, -10]",
            "- Event window: [-1, +1]",
            "- Significance rule: abs(SCAR) >= 1.96",
            "- Market model: asset_return = alpha + beta * benchmark_return",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assert_no_market_outcome_inputs() -> None:
    """Document and guard the V3 selection stage against market outcome paths."""

    forbidden_names = {"prices", "car_results"}
    cwd = Path.cwd().resolve()
    if any(part in forbidden_names for part in cwd.parts):
        raise RuntimeError("V3 selection must not run from price or CAR-result directories.")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Build V3 held-out validation artifacts.")
    parser.add_argument("--candidates", default=str(DEFAULT_V3_CANDIDATES))
    parser.add_argument("--output-dir", default=str(DEFAULT_V3_DIR))
    parser.add_argument("--kb", default=str(DEFAULT_KB_PATH))
    parser.add_argument("--v2-manifest", default=str(DEFAULT_V2_MANIFEST))
    parser.add_argument("--prior-snapshot-dir", default=str(DEFAULT_V1_V2_SNAPSHOT_DIR))
    parser.add_argument("--target-events", type=int, default=DEFAULT_TARGET_EVENTS)
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""

    args = parse_args()
    result = build_v3_validation_set(
        candidate_path=args.candidates,
        output_dir=args.output_dir,
        kb_path=args.kb,
        v2_manifest_path=args.v2_manifest,
        prior_snapshot_dir=args.prior_snapshot_dir,
        target_events=args.target_events,
        rebuild=args.rebuild,
    )
    print("V3 validation set freeze complete.")
    print(f"candidates: {result['candidate_count']}")
    print(f"eligible: {result['eligible_count']}")
    print(f"accepted_events: {result['accepted_count']}")
    print(f"snapshots: {result['snapshot_count']}")
    print(f"event_ids: {', '.join(result['event_ids'])}")
    print(f"output_dir: {result['output_dir']}")
    if result["snapshot_failures"]:
        print(f"snapshot_failures: {len(result['snapshot_failures'])}")


if __name__ == "__main__":
    main()
