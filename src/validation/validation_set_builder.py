"""Build held-out geopolitical validation-event manifests.

The builder screens candidate events before CAR evaluation. It must not inspect
CAR outputs, post-event returns, hit labels, or GeoRisk-vs-baseline performance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

from src.agents.event_analyst import analyze_event
from src.agents.market_mapper import map_assets
from src.pipeline import run_pipeline
from src.schemas import TransmissionChain
from src.validation.car_calculator import MarketModelConfig
from src.validation.car_models import BaselineExposure, PredictedExposure, ValidationEvent
from src.validation.event_screening import accepted_validation_events
from src.validation.prediction_snapshot import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SNAPSHOT_DIR,
    SNAPSHOT_VERSION_V2,
    create_full_pipeline_prediction_snapshot,
    predicted_exposure_from_evidence_result,
    load_validation_events,
    save_prediction_snapshot,
    snapshot_file_path,
)


DEFAULT_CANDIDATE_PATH = Path("data/validation_event_candidates.json")
DEFAULT_KB_PATH = Path("data/historical_cases.json")
DEFAULT_SELECTION_DIR = Path("data/validation_selection")
DEFAULT_RANDOM_SEED = 42
DEFAULT_MAX_EVENTS = 10
INCIDENT_REJECTION_SCORE = 0.72
MIN_EVENT_TEXT_WORDS = 12
MIN_PRICE_HISTORY_DATE = pd.Timestamp("2000-01-01")
DEFAULT_BASELINE_EXPOSURES = [
    {
        "symbol": "QQQ",
        "node": "broad_market_growth",
        "asset_type": "equity_etf",
        "baseline_type": "fixed_broad_market_baseline",
    },
    {
        "symbol": "XLF",
        "node": "financials",
        "asset_type": "equity_etf",
        "baseline_type": "fixed_sector_baseline",
    },
    {
        "symbol": "XLV",
        "node": "healthcare",
        "asset_type": "equity_etf",
        "baseline_type": "fixed_sector_baseline",
    },
]


@dataclass(frozen=True)
class CandidateScreen:
    """Screening result for one candidate validation event."""

    candidate: dict[str, Any]
    accepted: bool
    rejection_reasons: list[str]
    prediction_exposures: list[dict[str, Any]]
    overlap_report: dict[str, Any]


def build_validation_set(
    candidate_path: str | Path = DEFAULT_CANDIDATE_PATH,
    kb_path: str | Path = DEFAULT_KB_PATH,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    selection_dir: str | Path = DEFAULT_SELECTION_DIR,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    max_events: int = DEFAULT_MAX_EVENTS,
    seed: int = DEFAULT_RANDOM_SEED,
    rebuild: bool = False,
    config: MarketModelConfig | None = None,
) -> dict[str, Any]:
    """Build or update a held-out validation manifest from candidate events."""

    config = config or MarketModelConfig()
    candidates = load_candidate_events(candidate_path)
    kb_cases = load_historical_cases(kb_path)
    existing_events = load_existing_manifest_events(manifest_path)
    existing_accepted = accepted_validation_events(existing_events)
    preserved_events = [] if rebuild else existing_events
    preserved_accepted_ids = {
        event.event_id for event in ([] if rebuild else existing_accepted)
    }

    screens = [
        screen_candidate(candidate, kb_cases, config)
        for candidate in candidates
    ]
    available_slots = max(0, max_events - len(preserved_accepted_ids))
    selectable = [
        screen
        for screen in screens
        if screen.accepted and candidate_event_id(screen.candidate) not in preserved_accepted_ids
    ]
    selected_screens = select_diverse_events(selectable, available_slots, seed)
    selected_events = [
        validation_event_from_screen(screen)
        for screen in selected_screens
    ]
    final_events = [*preserved_events, *selected_events]

    manifest_output = write_validation_manifest(final_events, manifest_path)
    snapshot_paths = freeze_validation_snapshots(
        events=accepted_validation_events(final_events),
        snapshot_dir=snapshot_dir,
        rebuild=rebuild,
    )
    manifest_hash = sha256_file(manifest_output)
    write_audit_artifacts(
        selection_dir=selection_dir,
        screens=screens,
        selected_screens=selected_screens,
        preserved_accepted_ids=sorted(preserved_accepted_ids),
        candidates=candidates,
        kb_cases=kb_cases,
        max_events=max_events,
        seed=seed,
        rebuild=rebuild,
        manifest_path=manifest_path,
        kb_path=kb_path,
        manifest_hash=manifest_hash,
        snapshot_paths=snapshot_paths,
    )
    return {
        "candidate_count": len(candidates),
        "accepted_candidate_count": sum(1 for screen in screens if screen.accepted),
        "rejected_candidate_count": sum(1 for screen in screens if not screen.accepted),
        "selected_event_ids": [
            candidate_event_id(screen.candidate) for screen in selected_screens
        ],
        "preserved_accepted_event_ids": sorted(preserved_accepted_ids),
        "manifest_path": str(manifest_path),
        "selection_dir": str(selection_dir),
        "manifest_hash": manifest_hash,
        "snapshot_count": len(snapshot_paths),
    }


def load_candidate_events(path: str | Path) -> list[dict[str, Any]]:
    """Load structured validation-event candidates from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("candidates", [])
    if not isinstance(payload, list):
        raise ValueError("validation event candidate file must contain a list or candidates key.")
    return [dict(candidate) for candidate in payload]


def load_historical_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load historical KB cases used only for incident-overlap screening."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("historical_cases.json must contain a list.")
    return [dict(case) for case in payload]


def load_existing_manifest_events(path: str | Path) -> list[ValidationEvent]:
    """Load an existing manifest, returning no events when it is absent."""

    manifest = Path(path)
    if not manifest.exists():
        return []
    return load_validation_events(manifest)


def screen_candidate(
    candidate: dict[str, Any],
    kb_cases: list[dict[str, Any]],
    config: MarketModelConfig,
) -> CandidateScreen:
    """Apply objective pre-outcome eligibility checks to one candidate."""

    reasons: list[str] = []
    event_id = candidate_event_id(candidate)
    event_text = candidate_text(candidate)
    parsed_date = pd.to_datetime(candidate.get("event_date"), errors="coerce")

    if not event_id:
        reasons.append("missing_event_id")
    if pd.isna(parsed_date):
        reasons.append("missing_or_invalid_event_date")
    else:
        if not has_sufficient_calendar_room(pd.Timestamp(parsed_date), config):
            reasons.append("insufficient_calendar_room_for_car_windows")
    if len(event_text.split()) < MIN_EVENT_TEXT_WORDS:
        reasons.append("insufficient_contemporaneous_text")

    overlap_report = find_kb_overlap(candidate, kb_cases)
    if overlap_report["incident_level_overlap"]:
        reasons.append("incident_level_overlap_with_kb")

    exposures: list[dict[str, Any]] = []
    if not reasons:
        try:
            exposures = generate_prediction_exposures(candidate)
        except Exception as exc:
            reasons.append(f"prediction_generation_failed:{type(exc).__name__}")
            exposures = []
        if not exposures:
            reasons.append("no_mapped_candidate_exposure")

    return CandidateScreen(
        candidate=candidate,
        accepted=not reasons,
        rejection_reasons=reasons,
        prediction_exposures=exposures,
        overlap_report=overlap_report,
    )


def find_kb_overlap(candidate: dict[str, Any], kb_cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Find closest KB cases and flag incident-level overlap."""

    scored = [
        score_candidate_case_overlap(candidate, case)
        for case in kb_cases
    ]
    scored.sort(key=lambda item: item["score"], reverse=True)
    closest = scored[:3]
    incident_overlap = bool(closest and closest[0]["score"] >= INCIDENT_REJECTION_SCORE)
    return {
        "candidate_event_id": candidate_event_id(candidate),
        "incident_level_overlap": incident_overlap,
        "closest_cases": closest,
    }


def score_candidate_case_overlap(candidate: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Score incident-level overlap using dates, type, entities, and text."""

    candidate_date = pd.to_datetime(candidate.get("event_date"), errors="coerce")
    case_date = pd.to_datetime(case.get("date"), errors="coerce")
    days_apart = None
    date_score = 0.0
    if not pd.isna(candidate_date) and not pd.isna(case_date):
        days_apart = abs((pd.Timestamp(candidate_date) - pd.Timestamp(case_date)).days)
        if days_apart <= 3:
            date_score = 1.0
        elif days_apart <= 14:
            date_score = 0.7
        elif days_apart <= 45:
            date_score = 0.35

    candidate_type = normalize_text(str(candidate.get("event_type") or ""))
    case_type = normalize_text(str(case.get("event_type") or ""))
    type_score = SequenceMatcher(None, candidate_type, case_type).ratio() if candidate_type and case_type else 0.0

    candidate_entities = extract_entities(candidate)
    case_entities = extract_case_entities(case)
    entity_score = jaccard(candidate_entities, case_entities)
    text_score = SequenceMatcher(
        None,
        normalize_text(candidate_text(candidate)),
        normalize_text(case_text(case)),
    ).ratio()

    score = (
        0.35 * date_score
        + 0.25 * entity_score
        + 0.20 * type_score
        + 0.20 * text_score
    )
    return {
        "case_id": case.get("event_id") or case.get("case_id"),
        "case_name": case.get("event_name") or case.get("title"),
        "case_date": case.get("date"),
        "score": round(score, 4),
        "days_apart": days_apart,
        "date_score": round(date_score, 4),
        "event_type_similarity": round(type_score, 4),
        "entity_overlap": round(entity_score, 4),
        "text_similarity": round(text_score, 4),
        "shared_entities": sorted(candidate_entities & case_entities),
    }


def generate_prediction_exposures(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate formal GeoRisk exposures from final EvidenceResult objects.

    This uses the same full pipeline as normal analysis and deliberately raises
    if retrieval, transmission building, mapping, or evidence grading fails.
    Formal validation must not create normal-looking fallback exposures.
    """

    report = run_pipeline(candidate_text(candidate), event_analyzer="rule")
    return [
        predicted_exposure_from_evidence_result(
            candidate_event_id(candidate),
            result,
        ).model_dump(mode="json")
        for result in report.evidence_results
    ]


def generate_mapping_only_exposures(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate smoke-test fallback exposures without retrieval or market outcomes.

    This helper is intentionally not called by formal validation snapshot
    generation. It exists only for explicit lightweight smoke tests.
    """

    event = analyze_event(candidate_text(candidate))
    chain = TransmissionChain(
        affected_nodes=list(event.supply_chain_nodes),
        rationale="Validation-set fallback mapping from rule-analyzed event nodes.",
        limitations=["Retrieval-backed evidence grading was unavailable during validation-set construction."],
    )
    assets = map_assets(event, chain)
    return [
        PredictedExposure(
            event_id=candidate_event_id(candidate),
            symbol=asset.ticker or asset.asset_id,
            node=asset.supply_chain_node or "unknown",
            asset_type=asset.asset_type or "unknown",
            confidence=0.35,
            evidence_label="inference_only",
            source="georisk",
        ).model_dump(mode="json")
        for asset in assets
        if asset.ticker or asset.asset_id
    ]


def select_diverse_events(
    screens: list[CandidateScreen],
    max_events: int,
    seed: int,
) -> list[CandidateScreen]:
    """Select eligible events deterministically while spreading event types."""

    if max_events <= 0:
        return []
    ordered = sorted(
        screens,
        key=lambda screen: (
            str(screen.candidate.get("event_type") or ""),
            str(screen.candidate.get("event_date") or ""),
            candidate_event_id(screen.candidate),
        ),
    )
    selected: list[CandidateScreen] = []
    used_event_types: set[str] = set()

    for screen in ordered:
        event_type = str(screen.candidate.get("event_type") or "unknown")
        if event_type in used_event_types:
            continue
        selected.append(screen)
        used_event_types.add(event_type)
        if len(selected) >= max_events:
            return selected

    for screen in ordered:
        if screen in selected:
            continue
        selected.append(screen)
        if len(selected) >= max_events:
            return selected

    return selected


def validation_event_from_screen(screen: CandidateScreen) -> ValidationEvent:
    """Convert an accepted screen into the frozen validation manifest schema."""

    candidate = screen.candidate
    return ValidationEvent(
        event_id=candidate_event_id(candidate),
        event_date=str(candidate["event_date"]),
        event_description=candidate_text(candidate),
        event_type=candidate.get("event_type"),
        notes=str(candidate.get("notes") or ""),
        held_out_from_kb=True,
        clear_t0=True,
        clean_estimation_window=True,
        low_confounding=True,
        status="accepted",
        predicted_exposures=[
            PredictedExposure.model_validate(exposure)
            for exposure in screen.prediction_exposures
        ],
        baseline_assets=construct_baseline_exposures(),
    )


def construct_baseline_exposures() -> list[BaselineExposure]:
    """Return fixed outcome-independent baseline exposures for every event.

    The baseline uses the same ETF basket for all held-out events before any
    price data is loaded: QQQ as a broad growth/control ETF, plus XLF and XLV
    as broad sector controls. No CAR or return data is used to choose them.
    """

    return [
        BaselineExposure.model_validate({**baseline, "source": "baseline"})
        for baseline in DEFAULT_BASELINE_EXPOSURES
    ]


def freeze_validation_snapshots(
    events: list[ValidationEvent],
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    rebuild: bool = False,
) -> list[Path]:
    """Create missing V2 full-pipeline snapshots without overwriting V1 files."""

    paths: list[Path] = []
    output_dir = Path(snapshot_dir)
    for event in events:
        snapshot_path = snapshot_file_path(
            output_dir,
            event.event_id,
            SNAPSHOT_VERSION_V2,
        )
        if snapshot_path.exists() and not rebuild:
            paths.append(snapshot_path)
            continue
        snapshot = create_full_pipeline_prediction_snapshot(event)
        paths.append(save_prediction_snapshot(snapshot, output_dir))
    return paths


def write_validation_manifest(events: list[ValidationEvent], path: str | Path) -> Path:
    """Write validation events YAML in the downstream manifest format."""

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to write validation_events.yaml.") from exc

    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "validation_events": [
            event.model_dump(mode="json")
            for event in events
        ]
    }
    manifest_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return manifest_path


def write_audit_artifacts(
    selection_dir: str | Path,
    screens: list[CandidateScreen],
    selected_screens: list[CandidateScreen],
    preserved_accepted_ids: list[str],
    candidates: list[dict[str, Any]],
    kb_cases: list[dict[str, Any]],
    max_events: int,
    seed: int,
    rebuild: bool,
    manifest_path: str | Path,
    kb_path: str | Path,
    manifest_hash: str,
    snapshot_paths: list[Path],
) -> None:
    """Write reproducibility artifacts for candidate screening and selection."""

    output_dir = Path(selection_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    accepted = [screen_record(screen) for screen in screens if screen.accepted]
    rejected = [screen_record(screen) for screen in screens if not screen.accepted]

    write_json(output_dir / "accepted_events.json", accepted)
    write_json(output_dir / "rejected_events.json", rejected)
    write_json(
        output_dir / "kb_overlap_report.json",
        [screen.overlap_report for screen in screens],
    )
    write_candidate_screening_csv(output_dir / "candidate_screening.csv", screens)
    metadata = {
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "final_selected_event_ids": [
            candidate_event_id(screen.candidate) for screen in selected_screens
        ],
        "preserved_accepted_event_ids": preserved_accepted_ids,
        "kb_case_count": len(kb_cases),
        "kb_version": {
            "case_count": len(kb_cases),
            "sha256": sha256_file(kb_path) if Path(kb_path).exists() else None,
        },
        "manifest_hash": manifest_hash,
        "snapshot_count": len(snapshot_paths),
        "selection_rules": {
            "max_events": max_events,
            "incident_rejection_score": INCIDENT_REJECTION_SCORE,
            "ordering": "event_type,event_date,event_id; one pass for event-type diversity, then fill remaining slots",
            "outcome_data_used": False,
            "car_outputs_read": False,
            "manifest_rebuild": rebuild,
            "manifest_path": str(manifest_path),
        },
        "random_seed": seed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / "selection_metadata.json", metadata)
    write_final_validation_audit(
        path=output_dir / "final_validation_audit.md",
        screens=screens,
        selected_screens=selected_screens,
        candidates=candidates,
        kb_cases=kb_cases,
        metadata=metadata,
        snapshot_paths=snapshot_paths,
    )


def write_candidate_screening_csv(path: str | Path, screens: list[CandidateScreen]) -> Path:
    """Write one-row-per-candidate screening output."""

    fieldnames = [
        "event_id",
        "event_date",
        "event_type",
        "accepted",
        "rejection_reasons",
        "closest_kb_case",
        "closest_kb_score",
        "exposure_count",
    ]
    csv_path = Path(path)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for screen in screens:
            closest = (screen.overlap_report.get("closest_cases") or [{}])[0]
            writer.writerow(
                {
                    "event_id": candidate_event_id(screen.candidate),
                    "event_date": screen.candidate.get("event_date"),
                    "event_type": screen.candidate.get("event_type"),
                    "accepted": screen.accepted,
                    "rejection_reasons": ";".join(screen.rejection_reasons),
                    "closest_kb_case": closest.get("case_id"),
                    "closest_kb_score": closest.get("score"),
                    "exposure_count": len(screen.prediction_exposures),
                }
            )
    return csv_path


def write_final_validation_audit(
    path: str | Path,
    screens: list[CandidateScreen],
    selected_screens: list[CandidateScreen],
    candidates: list[dict[str, Any]],
    kb_cases: list[dict[str, Any]],
    metadata: dict[str, Any],
    snapshot_paths: list[Path],
) -> Path:
    """Write the final freeze-stage audit report without CAR performance."""

    output = Path(path)
    snapshot_by_event_id = {
        snapshot_path.stem.removesuffix("_snapshot"): snapshot_path
        for snapshot_path in snapshot_paths
    }
    reason_counts = Counter(
        reason
        for screen in screens
        for reason in screen.rejection_reasons
    )
    valid_date_count = sum(
        not pd.isna(pd.to_datetime(candidate.get("event_date"), errors="coerce"))
        for candidate in candidates
    )
    sufficient_description_count = sum(
        len(candidate_text(candidate).split()) >= MIN_EVENT_TEXT_WORDS
        for candidate in candidates
    )
    possible_overlap_count = sum(
        bool(candidate.get("possible_kb_overlap"))
        for candidate in candidates
    )
    collection_metadata = load_optional_json(
        Path("data/validation_candidates/collection_metadata.json")
    )

    lines = [
        "# Final Held-Out Validation Audit",
        "",
        "This audit covers event selection and snapshot freezing only. It does not inspect prices, returns, CAR, standardized CAR, hit labels, or baseline performance.",
        "",
        "## Summary",
        "",
        f"- Raw candidates: {collection_metadata.get('raw_article_count', 'n/a')}",
        f"- Deduplicated incidents: {collection_metadata.get('deduplicated_incident_count', 'n/a')}",
        f"- Candidate records loaded: {len(candidates)}",
        f"- Candidates with valid event dates: {valid_date_count}",
        f"- Candidates with sufficient descriptions: {sufficient_description_count}",
        f"- Possible KB overlaps flagged at collection: {possible_overlap_count}",
        f"- Rejected candidates: {sum(1 for screen in screens if not screen.accepted)}",
        f"- Eligible candidates: {sum(1 for screen in screens if screen.accepted)}",
        f"- Final selected events: {len(selected_screens)}",
        f"- KB case count: {len(kb_cases)}",
        f"- KB hash: `{metadata.get('kb_version', {}).get('sha256')}`",
        f"- Manifest hash: `{metadata.get('manifest_hash')}`",
        f"- Selection rule: {metadata['selection_rules']['ordering']}",
        f"- Random seed: {metadata.get('random_seed')}",
        "",
        "## Rejection Reasons",
        "",
        "| Reason | Count |",
        "| --- | ---: |",
    ]
    if reason_counts:
        for reason, count in sorted(reason_counts.items()):
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("| none | 0 |")

    lines.extend(
        [
            "",
            "## Baseline Construction",
            "",
            "Each accepted event receives the same fixed, outcome-independent baseline basket before market data is loaded: QQQ (broad growth/control ETF), XLF (financial-sector ETF), and XLV (healthcare-sector ETF). The basket is not selected from post-event returns, CAR, hit labels, or GeoRisk-vs-baseline performance.",
            "",
            "## Final Events",
            "",
            "| event_id | event_date | headline | mechanism | region | closest KB analog | held-out rationale | GeoRisk exposures | baseline exposures | snapshot path |",
            "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for screen in selected_screens:
        candidate = screen.candidate
        event_id = candidate_event_id(candidate)
        closest = (screen.overlap_report.get("closest_cases") or [{}])[0]
        closest_label = _closest_case_label(closest)
        rationale = "Distinct incident-level candidate; closest KB score below rejection threshold."
        if closest.get("days_apart") is not None:
            rationale += f" Closest analog is {closest.get('days_apart')} days apart."
        lines.append(
            "| "
            + " | ".join(
                [
                    event_id,
                    str(candidate.get("event_date") or ""),
                    _escape_md(str(candidate.get("headline") or "")),
                    _escape_md(str(candidate.get("event_type") or candidate.get("event_type_hint") or "")),
                    _escape_md(", ".join(_candidate_regions(candidate))),
                    _escape_md(closest_label),
                    _escape_md(rationale),
                    str(len(screen.prediction_exposures)),
                    str(len(DEFAULT_BASELINE_EXPOSURES)),
                    str(snapshot_by_event_id.get(event_id, "")),
                ]
            )
            + " |"
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def screen_record(screen: CandidateScreen) -> dict[str, Any]:
    """Return a JSON-safe screen record."""

    return {
        "candidate": screen.candidate,
        "accepted": screen.accepted,
        "rejection_reasons": screen.rejection_reasons,
        "prediction_exposure_count": len(screen.prediction_exposures),
        "prediction_exposures": screen.prediction_exposures,
        "overlap_report": screen.overlap_report,
    }


def has_sufficient_calendar_room(event_date: pd.Timestamp, config: MarketModelConfig) -> bool:
    """Check only date feasibility for CAR windows, never market outcomes."""

    earliest_offset = min(config.estimation_window_start, config.event_window_start, 0)
    latest_offset = max(config.estimation_window_end, config.event_window_end, 0)
    required_start = event_date + pd.Timedelta(days=int(earliest_offset * 7 / 5) - 14)
    required_end = event_date + pd.Timedelta(days=int(latest_offset * 7 / 5) + 14)
    now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
    return required_start >= MIN_PRICE_HISTORY_DATE and required_end <= now


def candidate_text(candidate: dict[str, Any]) -> str:
    """Return the frozen text used for pre-outcome GeoRisk prediction."""

    return " ".join(
        str(candidate.get(field) or "").strip()
        for field in ["headline", "event_text"]
        if str(candidate.get(field) or "").strip()
    ).strip()


def candidate_event_id(candidate: dict[str, Any]) -> str:
    """Return the builder event ID, accepting collector-style candidate IDs."""

    return str(candidate.get("event_id") or candidate.get("candidate_id") or "").strip()


def case_text(case: dict[str, Any]) -> str:
    """Return descriptive KB case text for incident-overlap screening."""

    values = [
        case.get("event_name"),
        case.get("summary"),
        case.get("retrieval_text"),
    ]
    return " ".join(str(value) for value in values if value)


def extract_entities(candidate: dict[str, Any]) -> set[str]:
    """Extract deterministic entity-like tokens from candidate metadata/text."""

    values: list[str] = []
    for field in ["regions", "countries", "entities"]:
        raw = candidate.get(field)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    values.append(candidate_text(candidate))
    return entity_tokens(" ".join(values))


def extract_case_entities(case: dict[str, Any]) -> set[str]:
    """Extract deterministic entity-like tokens from a KB case."""

    values: list[str] = []
    for field in ["regions", "countries", "affected_assets"]:
        raw = case.get(field)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    values.append(case_text(case))
    return entity_tokens(" ".join(values))


def entity_tokens(text: str) -> set[str]:
    """Return simple proper-noun/acronym tokens for incident comparison."""

    tokens = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b|\b[A-Z]{2,}\b", text)
    return {token.lower() for token in tokens}


def normalize_text(text: str) -> str:
    """Normalize text for deterministic fuzzy comparison."""

    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def jaccard(left: set[str], right: set[str]) -> float:
    """Return Jaccard overlap for two token sets."""

    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def write_json(path: str | Path, payload: Any) -> Path:
    """Write JSON with stable formatting."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def load_optional_json(path: str | Path) -> dict[str, Any]:
    """Load an optional JSON object, returning an empty dict if absent."""

    target = Path(path)
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: str | Path) -> str:
    """Return a SHA-256 hash for a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_regions(candidate: dict[str, Any]) -> list[str]:
    for field in ["regions", "regions_hint"]:
        values = candidate.get(field)
        if isinstance(values, list):
            return [str(value) for value in values]
    return []


def _closest_case_label(closest: dict[str, Any]) -> str:
    if not closest:
        return "none"
    return (
        f"{closest.get('case_id')} "
        f"(score={closest.get('score')}, date={closest.get('case_date')})"
    )


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for validation-set construction."""

    parser = argparse.ArgumentParser(
        description="Build a held-out validation event manifest from candidates.",
    )
    parser.add_argument("--candidates", default=str(DEFAULT_CANDIDATE_PATH))
    parser.add_argument("--kb", default=str(DEFAULT_KB_PATH))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--selection-dir", default=str(DEFAULT_SELECTION_DIR))
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def main() -> None:
    """CLI entry point for validation-set construction."""

    args = parse_args()
    result = build_validation_set(
        candidate_path=args.candidates,
        kb_path=args.kb,
        manifest_path=args.manifest,
        selection_dir=args.selection_dir,
        snapshot_dir=args.snapshot_dir,
        max_events=args.max_events,
        seed=args.seed,
        rebuild=args.rebuild,
    )
    print("Validation set build complete.")
    print(f"candidates: {result['candidate_count']}")
    print(f"accepted_candidates: {result['accepted_candidate_count']}")
    print(f"rejected_candidates: {result['rejected_candidate_count']}")
    print(f"preserved_accepted_events: {len(result['preserved_accepted_event_ids'])}")
    print(f"selected_new_events: {len(result['selected_event_ids'])}")
    print(f"manifest: {result['manifest_path']}")
    print(f"audit_dir: {result['selection_dir']}")
    print(f"manifest_hash: {result['manifest_hash']}")
    print(f"snapshots: {result['snapshot_count']}")


if __name__ == "__main__":
    main()
