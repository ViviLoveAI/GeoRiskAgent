"""Screen source-backed V4 held-out candidate events before prediction.

This module is intentionally upstream of prediction. It does not run GeoRisk,
does not import the pipeline, does not read prices, and does not compute CAR.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

from src.validation.v4_heldout_protocol import (
    DEFAULT_PROTOCOL_DIR,
    assert_csv_has_no_outcome_columns,
    assert_freeze_manifest_ready,
    validate_no_outcome_columns,
)


DEFAULT_CANDIDATE_PATH = DEFAULT_PROTOCOL_DIR / "candidate_events.csv"
DEFAULT_SCREENING_OUTPUT = DEFAULT_PROTOCOL_DIR / "candidate_event_screening.csv"
DEFAULT_SUMMARY_OUTPUT = DEFAULT_PROTOCOL_DIR / "candidate_event_screening_summary.json"
DEFAULT_PROVISIONAL_ACCEPTED_OUTPUT = DEFAULT_PROTOCOL_DIR / "provisional_accepted_events.csv"
DEFAULT_STATUS_PATH = DEFAULT_PROTOCOL_DIR / "heldout_status.json"
DEFAULT_KB_PATH = Path("data/historical_cases.json")
DEFAULT_V3_ACCEPTED_PATH = Path("data/validation_v3/accepted_events.csv")
DEFAULT_VALIDATION_EVENTS_PATH = Path("data/validation_events.yaml")
DEFAULT_DEV_DIR = Path("data/topk_sensitivity_v4")

OUTCOME_LEAKAGE_PATTERNS = [
    r"\blater\s+(rose|fell|gained|declined|dropped|rallied|sold\s+off)\b",
    r"\bsubsequently\s+(rose|fell|gained|declined|dropped|rallied)\b",
    r"\bmarket\s+reaction\b",
    r"\bafter\s+the\s+event\s+(shares|stocks|prices)\b",
    r"\b(car|scar|abnormal\s+return|standardized\s+car)\b",
    r"\b(realized\s+return|realized\s+direction)\b",
]

SCREENING_FIELDS = [
    "candidate_id",
    "event_name",
    "event_date",
    "t0_date",
    "event_type",
    "eligibility_status",
    "exact_kb_overlap",
    "near_duplicate_overlap",
    "development_overlap",
    "prior_validation_overlap",
    "t0_valid",
    "source_valid",
    "outcome_leakage_detected",
    "kb_overlap_status",
    "development_overlap_status",
    "prior_validation_overlap_status",
    "closest_kb_event_id",
    "closest_kb_score",
    "closest_development_event_id",
    "closest_development_score",
    "closest_prior_validation_event_id",
    "closest_prior_validation_score",
    "reason",
]

PROVISIONAL_ACCEPTED_FIELDS = [
    "candidate_id",
    "event_name",
    "event_date",
    "t0_date",
    "event_type",
    "primary_source",
    "secondary_source",
    "selection_rationale",
]

EXACT_OVERLAP_THRESHOLD = 0.94
NEAR_DUPLICATE_THRESHOLD = 0.86
TEXT_MIN_WORDS = 10


@dataclass(frozen=True)
class CandidateRecord:
    """One source-backed candidate before any V4 prediction is run."""

    raw: dict[str, str]

    @property
    def candidate_id(self) -> str:
        return field_value(self.raw, "candidate_id", "event_id")

    @property
    def event_name(self) -> str:
        return field_value(self.raw, "event_name", "headline")

    @property
    def event_date(self) -> str:
        return field_value(self.raw, "event_date")

    @property
    def t0_date(self) -> str:
        return field_value(self.raw, "t0_date")

    @property
    def event_text(self) -> str:
        return field_value(self.raw, "short_description", "event_text")

    @property
    def event_type(self) -> str:
        return field_value(self.raw, "event_type_if_preoutcome_observable", "event_type")


@dataclass(frozen=True)
class ReferenceEvent:
    """One prior event used only for overlap screening."""

    event_id: str
    event_date: str
    event_name: str
    event_text: str
    event_type: str
    source_group: str


@dataclass(frozen=True)
class ScreeningResult:
    """Eligibility result for one candidate."""

    candidate: CandidateRecord
    eligibility_status: str
    reasons: list[str]
    kb_overlap_status: str
    development_overlap_status: str
    prior_validation_overlap_status: str
    closest_kb: dict[str, Any]
    closest_development: dict[str, Any]
    closest_prior_validation: dict[str, Any]
    t0_valid: bool
    source_valid: bool
    outcome_leakage_detected: bool


def screen_v4_heldout_candidates(
    candidate_path: str | Path = DEFAULT_CANDIDATE_PATH,
    output_path: str | Path = DEFAULT_SCREENING_OUTPUT,
    summary_path: str | Path = DEFAULT_SUMMARY_OUTPUT,
    provisional_accepted_path: str | Path = DEFAULT_PROVISIONAL_ACCEPTED_OUTPUT,
    status_path: str | Path = DEFAULT_STATUS_PATH,
    kb_path: str | Path = DEFAULT_KB_PATH,
    v3_accepted_path: str | Path = DEFAULT_V3_ACCEPTED_PATH,
    validation_events_path: str | Path = DEFAULT_VALIDATION_EVENTS_PATH,
    development_dir: str | Path = DEFAULT_DEV_DIR,
    freeze_manifest_path: str | Path = Path("data/topk_sensitivity_v4/v4_final_freeze_manifest.json"),
) -> dict[str, Any]:
    """Screen held-out candidates and write auditable artifacts."""

    assert_freeze_manifest_ready(freeze_manifest_path)
    candidates = load_candidate_records(candidate_path)
    kb_events = load_historical_kb_reference_events(kb_path)
    development_events = load_development_reference_events(development_dir)
    prior_validation_events = load_prior_validation_reference_events(
        v3_accepted_path=v3_accepted_path,
        validation_events_path=validation_events_path,
    )

    results = [
        screen_candidate_record(
            candidate=candidate,
            kb_events=kb_events,
            development_events=development_events,
            prior_validation_events=prior_validation_events,
        )
        for candidate in candidates
    ]

    write_screening_csv(output_path, results)
    write_provisional_accepted_csv(provisional_accepted_path, results)
    summary = build_screening_summary(results)
    write_json(summary_path, summary)
    update_status_after_screening(status_path, candidate_count=len(candidates))
    return summary


def load_candidate_records(path: str | Path) -> list[CandidateRecord]:
    """Load candidate records from a CSV, rejecting outcome columns."""

    csv_path = Path(path)
    if not csv_path.exists():
        write_empty_candidate_file(csv_path)
        return []
    assert_csv_has_no_outcome_columns(csv_path)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        validate_no_outcome_columns(list(reader.fieldnames or []))
        return [
            CandidateRecord({key: (value or "").strip() for key, value in row.items()})
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]


def screen_candidate_record(
    candidate: CandidateRecord,
    kb_events: list[ReferenceEvent],
    development_events: list[ReferenceEvent],
    prior_validation_events: list[ReferenceEvent],
) -> ScreeningResult:
    """Screen one candidate without running prediction or reading outcomes."""

    reasons: list[str] = []
    t0_valid = valid_date(candidate.t0_date)
    source_valid = has_sufficient_source(candidate.raw)
    outcome_leakage = detect_outcome_leakage(candidate.raw)

    if not candidate.candidate_id:
        reasons.append("missing_candidate_id")
    if not candidate.event_name:
        reasons.append("missing_event_name")
    if not valid_date(candidate.event_date):
        reasons.append("invalid_event_date")
    if not t0_valid:
        reasons.append("unclear_t0")
    if len(candidate.event_text.split()) < TEXT_MIN_WORDS:
        reasons.append("insufficient_event_text")
    if not source_valid:
        reasons.append("insufficient_sources")
    if outcome_leakage:
        reasons.append("outcome_leakage_detected")

    closest_kb = closest_overlap(candidate, kb_events)
    closest_development = closest_overlap(candidate, development_events)
    closest_prior_validation = closest_overlap(candidate, prior_validation_events)

    kb_status = overlap_status(closest_kb)
    development_status = overlap_status(closest_development)
    prior_status = overlap_status(closest_prior_validation)

    if kb_status in {"exact_event_overlap", "near_duplicate_event"}:
        reasons.append("kb_event_overlap")
    if development_status in {"exact_event_overlap", "near_duplicate_event"}:
        reasons.append("development_event_overlap")
    if prior_status in {"exact_event_overlap", "near_duplicate_event"}:
        reasons.append("prior_validation_overlap")

    if "outcome_leakage_detected" in reasons:
        status = "reject_outcome_leakage"
    elif "kb_event_overlap" in reasons:
        status = "reject_exact_kb_overlap"
    elif "development_event_overlap" in reasons:
        status = "reject_development_overlap"
    elif "prior_validation_overlap" in reasons:
        status = "reject_prior_validation_overlap"
    elif "unclear_t0" in reasons or "invalid_event_date" in reasons:
        status = "reject_unclear_t0"
    elif "insufficient_sources" in reasons:
        status = "reject_insufficient_sources"
    elif reasons:
        status = "needs_manual_review"
    else:
        status = "eligible"

    return ScreeningResult(
        candidate=candidate,
        eligibility_status=status,
        reasons=reasons,
        kb_overlap_status=kb_status,
        development_overlap_status=development_status,
        prior_validation_overlap_status=prior_status,
        closest_kb=closest_kb,
        closest_development=closest_development,
        closest_prior_validation=closest_prior_validation,
        t0_valid=t0_valid,
        source_valid=source_valid,
        outcome_leakage_detected=outcome_leakage,
    )


def closest_overlap(candidate: CandidateRecord, references: list[ReferenceEvent]) -> dict[str, Any]:
    """Return the highest-scoring reference overlap."""

    if not references:
        return empty_overlap()
    scored = [score_overlap(candidate, reference) for reference in references]
    return max(scored, key=lambda item: item["score"])


def score_overlap(candidate: CandidateRecord, reference: ReferenceEvent) -> dict[str, Any]:
    """Score incident-level overlap while allowing thematic generalization."""

    candidate_id = normalize_identifier(candidate.candidate_id)
    reference_id = normalize_identifier(reference.event_id)
    id_score = 1.0 if candidate_id and candidate_id == reference_id else 0.0
    date_score = 1.0 if same_date(candidate.event_date, reference.event_date) else 0.0
    name_score = text_similarity(candidate.event_name, reference.event_name)
    text_score = text_similarity(candidate.event_text, reference.event_text)
    type_score = text_similarity(candidate.event_type, reference.event_type)
    score = max(
        id_score,
        (0.35 * date_score) + (0.35 * name_score) + (0.20 * text_score) + (0.10 * type_score),
    )
    return {
        "event_id": reference.event_id,
        "event_date": reference.event_date,
        "event_name": reference.event_name,
        "source_group": reference.source_group,
        "score": round(score, 4),
        "same_date": bool(date_score),
        "name_similarity": round(name_score, 4),
        "text_similarity": round(text_score, 4),
        "event_type_similarity": round(type_score, 4),
    }


def overlap_status(overlap: dict[str, Any]) -> str:
    """Classify overlap as exact, near duplicate, thematic, or none."""

    score = float(overlap.get("score") or 0.0)
    type_similarity = float(overlap.get("event_type_similarity") or 0.0)
    if score >= EXACT_OVERLAP_THRESHOLD:
        return "exact_event_overlap"
    if score >= NEAR_DUPLICATE_THRESHOLD:
        return "near_duplicate_event"
    if type_similarity >= 0.82:
        return "same_event_family_but_independent"
    return "no_overlap"


def detect_outcome_leakage(row: dict[str, str]) -> bool:
    """Detect forbidden columns or obvious retrospective market wording."""

    validate_no_outcome_columns(list(row.keys()))
    text = " ".join(str(value or "") for value in row.values()).lower()
    return any(re.search(pattern, text) for pattern in OUTCOME_LEAKAGE_PATTERNS)


def has_sufficient_source(row: dict[str, str]) -> bool:
    """Require source-backed event metadata without requiring market outcomes."""

    primary = field_value(row, "primary_source", "source_url")
    secondary = field_value(row, "secondary_source", "source_name")
    source_date = field_value(row, "source_date", "source_published_at")
    return bool(primary and source_date and (secondary or primary.startswith("http")))


def load_historical_kb_reference_events(path: str | Path) -> list[ReferenceEvent]:
    """Load historical KB cases for incident-overlap screening."""

    kb_path = Path(path)
    if not kb_path.exists():
        return []
    payload = json.loads(kb_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return [
        ReferenceEvent(
            event_id=str(case.get("event_id") or case.get("case_id") or ""),
            event_date=str(case.get("date") or case.get("event_date") or ""),
            event_name=str(case.get("event_name") or case.get("title") or ""),
            event_text=str(case.get("summary") or case.get("retrieval_text") or ""),
            event_type=str(case.get("event_type") or ""),
            source_group="historical_kb",
        )
        for case in payload
    ]


def load_prior_validation_reference_events(
    v3_accepted_path: str | Path = DEFAULT_V3_ACCEPTED_PATH,
    validation_events_path: str | Path = DEFAULT_VALIDATION_EVENTS_PATH,
) -> list[ReferenceEvent]:
    """Load prior validation events without reading CAR outputs."""

    events: list[ReferenceEvent] = []
    events.extend(load_csv_reference_events(v3_accepted_path, "prior_validation_v3"))
    yaml_path = Path(validation_events_path)
    if yaml_path.exists():
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            for raw in payload.get("validation_events", []) or []:
                events.append(
                    ReferenceEvent(
                        event_id=str(raw.get("event_id") or ""),
                        event_date=str(raw.get("event_date") or ""),
                        event_name=str(raw.get("event_description") or "")[:120],
                        event_text=str(raw.get("event_description") or ""),
                        event_type=str(raw.get("event_type") or ""),
                        source_group="prior_validation_manifest",
                    )
                )
    return events


def load_development_reference_events(path: str | Path = DEFAULT_DEV_DIR) -> list[ReferenceEvent]:
    """Load V4 development event identifiers from diagnostic artifacts."""

    base = Path(path)
    events: dict[str, ReferenceEvent] = {}
    if not base.exists():
        return []
    for csv_path in base.glob("*.csv"):
        for event in load_csv_reference_events(csv_path, f"development:{csv_path.name}"):
            if event.event_id and event.event_id not in events:
                events[event.event_id] = event
    for json_path in base.glob("*.json"):
        for event in extract_reference_events_from_json(json_path):
            if event.event_id and event.event_id not in events:
                events[event.event_id] = event
    return list(events.values())


def load_csv_reference_events(path: str | Path, source_group: str) -> list[ReferenceEvent]:
    """Best-effort extraction of event-like records from a CSV."""

    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            event_id = field_value(row, "event_id", "candidate_id", "current_event_id")
            if not event_id:
                continue
            rows.append(
                ReferenceEvent(
                    event_id=event_id,
                    event_date=field_value(row, "event_date", "date", "t0_date"),
                    event_name=field_value(row, "event_name", "headline", "node"),
                    event_text=field_value(row, "event_text", "short_description", "summary", "rationale"),
                    event_type=field_value(row, "event_type", "mechanism_family", "canonical_family"),
                    source_group=source_group,
                )
            )
        return rows


def extract_reference_events_from_json(path: Path) -> list[ReferenceEvent]:
    """Extract event ids from JSON diagnostics without interpreting outcomes."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    records: list[ReferenceEvent] = []
    for raw in walk_json_objects(payload):
        event_id = field_value(raw, "event_id", "current_event_id", "candidate_id")
        if event_id:
            records.append(
                ReferenceEvent(
                    event_id=event_id,
                    event_date=field_value(raw, "event_date", "date", "t0_date"),
                    event_name=field_value(raw, "event_name", "headline", "node"),
                    event_text=field_value(raw, "event_text", "summary", "description", "rationale"),
                    event_type=field_value(raw, "event_type", "canonical_family", "mechanism_family"),
                    source_group=f"development:{path.name}",
                )
            )
    return records


def walk_json_objects(payload: Any) -> list[dict[str, Any]]:
    """Return all dict objects in a nested JSON-like payload."""

    found: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        found.append(payload)
        for value in payload.values():
            found.extend(walk_json_objects(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(walk_json_objects(item))
    return found


def build_screening_summary(results: list[ScreeningResult]) -> dict[str, Any]:
    """Summarize screening results without sealing a held-out manifest."""

    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.eligibility_status] = status_counts.get(result.eligibility_status, 0) + 1
    eligible = status_counts.get("eligible", 0)
    rejected = sum(count for status, count in status_counts.items() if status.startswith("reject_"))
    manual_review = status_counts.get("needs_manual_review", 0)
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(results),
        "eligible_count": eligible,
        "rejected_count": rejected,
        "manual_review_count": manual_review,
        "status_counts": status_counts,
        "candidate_pool_created": bool(results),
        "provisional_accepted_count": eligible,
        "predictions_frozen": False,
        "car_run": False,
        "outcome_data_used": False,
        "v4_prediction_run": False,
    }


def write_screening_csv(path: str | Path, results: list[ScreeningResult]) -> Path:
    """Write per-candidate screening rows."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCREENING_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(screening_row(result))
    return output


def write_provisional_accepted_csv(path: str | Path, results: list[ScreeningResult]) -> Path:
    """Write eligible candidates only; this is not a sealed manifest."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROVISIONAL_ACCEPTED_FIELDS)
        writer.writeheader()
        for result in results:
            if result.eligibility_status != "eligible":
                continue
            row = result.candidate.raw
            writer.writerow(
                {
                    "candidate_id": result.candidate.candidate_id,
                    "event_name": result.candidate.event_name,
                    "event_date": result.candidate.event_date,
                    "t0_date": result.candidate.t0_date,
                    "event_type": result.candidate.event_type,
                    "primary_source": field_value(row, "primary_source", "source_url"),
                    "secondary_source": field_value(row, "secondary_source", "source_name"),
                    "selection_rationale": field_value(row, "selection_rationale", "selection_notes"),
                }
            )
    return output


def screening_row(result: ScreeningResult) -> dict[str, Any]:
    """Serialize a screening result to a CSV row."""

    return {
        "candidate_id": result.candidate.candidate_id,
        "event_name": result.candidate.event_name,
        "event_date": result.candidate.event_date,
        "t0_date": result.candidate.t0_date,
        "event_type": result.candidate.event_type,
        "eligibility_status": result.eligibility_status,
        "exact_kb_overlap": result.kb_overlap_status == "exact_event_overlap",
        "near_duplicate_overlap": any(
            status == "near_duplicate_event"
            for status in [
                result.kb_overlap_status,
                result.development_overlap_status,
                result.prior_validation_overlap_status,
            ]
        ),
        "development_overlap": result.development_overlap_status in {"exact_event_overlap", "near_duplicate_event"},
        "prior_validation_overlap": result.prior_validation_overlap_status in {"exact_event_overlap", "near_duplicate_event"},
        "t0_valid": result.t0_valid,
        "source_valid": result.source_valid,
        "outcome_leakage_detected": result.outcome_leakage_detected,
        "kb_overlap_status": result.kb_overlap_status,
        "development_overlap_status": result.development_overlap_status,
        "prior_validation_overlap_status": result.prior_validation_overlap_status,
        "closest_kb_event_id": result.closest_kb.get("event_id"),
        "closest_kb_score": result.closest_kb.get("score"),
        "closest_development_event_id": result.closest_development.get("event_id"),
        "closest_development_score": result.closest_development.get("score"),
        "closest_prior_validation_event_id": result.closest_prior_validation.get("event_id"),
        "closest_prior_validation_score": result.closest_prior_validation.get("score"),
        "reason": ";".join(result.reasons),
    }


def update_status_after_screening(path: str | Path, candidate_count: int) -> None:
    """Update protocol status without marking held-out events as sealed."""

    status_path = Path(path)
    if status_path.exists():
        status = json.loads(status_path.read_text(encoding="utf-8"))
    else:
        status = {}
    status.update(
        {
            "candidate_pool_created": candidate_count > 0,
            "candidate_events_populated": candidate_count > 0,
            "accepted_events_populated": False,
            "heldout_events_created": False,
            "predictions_frozen": False,
            "price_inputs_prepared": False,
            "car_run": False,
        }
    )
    write_json(status_path, status)


def write_empty_candidate_file(path: Path) -> None:
    """Create the candidate CSV header when no source-backed candidates exist yet."""

    fields = [
        "candidate_id",
        "event_name",
        "event_date",
        "t0_date",
        "short_description",
        "primary_source",
        "secondary_source",
        "source_date",
        "event_type_if_preoutcome_observable",
        "regions",
        "countries",
        "first_order_shock_description",
        "selection_rationale",
        "notes",
    ]
    validate_no_outcome_columns(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(fields)


def empty_overlap() -> dict[str, Any]:
    """Return an empty overlap record."""

    return {
        "event_id": "",
        "event_date": "",
        "event_name": "",
        "source_group": "",
        "score": 0.0,
        "same_date": False,
        "name_similarity": 0.0,
        "text_similarity": 0.0,
        "event_type_similarity": 0.0,
    }


def valid_date(value: str) -> bool:
    """Return whether a date-like value is parseable."""

    return not pd.isna(pd.to_datetime(value, errors="coerce"))


def same_date(left: str, right: str) -> bool:
    """Return whether two date-like values resolve to the same calendar date."""

    left_date = pd.to_datetime(left, errors="coerce")
    right_date = pd.to_datetime(right, errors="coerce")
    if pd.isna(left_date) or pd.isna(right_date):
        return False
    return pd.Timestamp(left_date).date() == pd.Timestamp(right_date).date()


def text_similarity(left: str, right: str) -> float:
    """Return normalized text similarity."""

    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def normalize_identifier(value: str) -> str:
    """Normalize event identifiers for exact-id overlap."""

    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def normalize_text(value: str) -> str:
    """Normalize text for incident-overlap screening."""

    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def field_value(row: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string among possible field names."""

    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    """Write JSON with stable formatting."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    """Parse CLI args for candidate screening."""

    parser = argparse.ArgumentParser(description="Screen V4 held-out candidate events without prediction.")
    parser.add_argument("--candidates", default=str(DEFAULT_CANDIDATE_PATH))
    parser.add_argument("--output", default=str(DEFAULT_SCREENING_OUTPUT))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY_OUTPUT))
    parser.add_argument("--provisional-accepted", default=str(DEFAULT_PROVISIONAL_ACCEPTED_OUTPUT))
    parser.add_argument("--status", default=str(DEFAULT_STATUS_PATH))
    return parser.parse_args()


def main() -> None:
    """Run held-out candidate screening."""

    args = parse_args()
    summary = screen_v4_heldout_candidates(
        candidate_path=args.candidates,
        output_path=args.output,
        summary_path=args.summary,
        provisional_accepted_path=args.provisional_accepted,
        status_path=args.status,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
