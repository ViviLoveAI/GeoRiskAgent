"""Create the untouched V4 held-out validation protocol scaffold.

This module defines guardrails and empty artifacts for a future V4 held-out
validation run. It deliberately does not select events, freeze predictions,
fetch prices, run CAR, or inspect market outcomes.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "v4_heldout_protocol_v1"
DEFAULT_PROTOCOL_DIR = Path("data/validation_v4")
DEFAULT_FREEZE_MANIFEST_PATH = Path(
    "data/topk_sensitivity_v4/v4_final_freeze_manifest.json"
)
DEFAULT_FREEZE_CHECKSUMS_PATH = Path(
    "data/topk_sensitivity_v4/v4_freeze_checksums.json"
)

REQUIRED_FREEZE_STATUS = "V4 DEVELOPMENT FROZEN"
REQUIRED_TOP_K = 10
REQUIRED_SUPPORT_THRESHOLD = 2
REQUIRED_TRANSMISSION_CONTEXT_VERSION = "transmission_context_v1"
REQUIRED_CANONICAL_FAMILY_VERSION = "canonical_family_v1"
REQUIRED_COMPATIBILITY_VERSION = "mechanism_compatibility_candidate_v1"

CANDIDATE_EVENT_FIELDS = [
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

ACCEPTED_EVENT_FIELDS = [
    "event_id",
    "event_date",
    "event_type",
    "clear_t0",
    "held_out_from_kb",
    "no_v1_v2_v3_overlap",
    "not_exact_kb_duplicate",
    "clean_estimation_window",
    "low_confounding",
    "accepted",
    "rejection_reasons",
    "screening_notes",
]

DISALLOWED_OUTCOME_COLUMNS = {
    "abnormal_return",
    "actual_return",
    "alpha",
    "benchmark_return",
    "car",
    "direction_correct",
    "event_window_return",
    "hit",
    "hit_rate",
    "market_reaction",
    "price_after",
    "price_before",
    "realized_return",
    "return",
    "scar",
    "standardized_car",
}


def create_v4_heldout_protocol(
    output_dir: str | Path = DEFAULT_PROTOCOL_DIR,
    freeze_manifest_path: str | Path = DEFAULT_FREEZE_MANIFEST_PATH,
    freeze_checksums_path: str | Path = DEFAULT_FREEZE_CHECKSUMS_PATH,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create empty V4 held-out protocol artifacts without selecting events."""

    output = Path(output_dir)
    freeze_manifest = assert_freeze_manifest_ready(freeze_manifest_path)
    freeze_checksums = load_json(freeze_checksums_path)

    output.mkdir(parents=True, exist_ok=True)
    templates_dir = output / "templates"
    raw_candidate_dir = output / "candidates" / "raw"
    snapshot_dir = output / "prediction_snapshots"
    car_results_dir = output / "car_results"
    for directory in (templates_dir, raw_candidate_dir, snapshot_dir, car_results_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest = build_protocol_manifest(
        freeze_manifest=freeze_manifest,
        freeze_manifest_path=Path(freeze_manifest_path),
        freeze_checksums_path=Path(freeze_checksums_path),
        freeze_checksums=freeze_checksums,
    )

    written = {
        "protocol_manifest": write_json_if_allowed(
            output / "v4_heldout_protocol_manifest.json",
            manifest,
            overwrite=overwrite,
        ),
        "protocol_markdown": write_text_if_allowed(
            output / "V4_HELDOUT_VALIDATION_PROTOCOL.md",
            render_protocol_markdown(manifest),
            overwrite=overwrite,
        ),
        "candidate_template": write_csv_template(
            templates_dir / "candidate_events_template.csv",
            CANDIDATE_EVENT_FIELDS,
            overwrite=overwrite,
        ),
        "accepted_template": write_csv_template(
            templates_dir / "accepted_events_template.csv",
            ACCEPTED_EVENT_FIELDS,
            overwrite=overwrite,
        ),
        "status": write_json_if_allowed(
            output / "heldout_status.json",
            build_initial_status(),
            overwrite=overwrite,
        ),
        "raw_candidates_gitkeep": write_text_if_allowed(
            raw_candidate_dir / ".gitkeep",
            "",
            overwrite=True,
        ),
        "snapshots_gitkeep": write_text_if_allowed(
            snapshot_dir / ".gitkeep",
            "",
            overwrite=True,
        ),
        "car_results_readme": write_text_if_allowed(
            car_results_dir / "DO_NOT_USE_BEFORE_SNAPSHOT_FREEZE.md",
            "CAR outputs are intentionally absent. Run CAR only after V4 held-out events and predictions are frozen.\n",
            overwrite=overwrite,
        ),
    }

    return {
        "protocol_version": PROTOCOL_VERSION,
        "output_dir": str(output),
        "written": {key: str(path) for key, path in written.items()},
        "heldout_events_created": False,
        "predictions_frozen": False,
        "car_run": False,
    }


def assert_freeze_manifest_ready(path: str | Path) -> dict[str, Any]:
    """Validate that the frozen V4 manifest matches the protocol requirements."""

    manifest = load_json(path)
    checks = {
        "freeze_status": manifest.get("freeze_status") == REQUIRED_FREEZE_STATUS,
        "top_k": manifest.get("retrieval", {}).get("top_k") == REQUIRED_TOP_K,
        "support_threshold": (
            manifest.get("support_policy", {}).get("support_threshold")
            == REQUIRED_SUPPORT_THRESHOLD
        ),
        "transmission_context_version": (
            manifest.get("mechanism_representation", {}).get("transmission_context_version")
            == REQUIRED_TRANSMISSION_CONTEXT_VERSION
        ),
        "canonical_family_version": (
            manifest.get("mechanism_representation", {}).get("canonical_family_version")
            == REQUIRED_CANONICAL_FAMILY_VERSION
        ),
        "mechanism_compatibility_version": (
            manifest.get("mechanism_representation", {}).get("mechanism_compatibility_version")
            == REQUIRED_COMPATIBILITY_VERSION
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"v4_freeze_manifest_not_ready:{','.join(failed)}")
    return manifest


def build_protocol_manifest(
    freeze_manifest: dict[str, Any],
    freeze_manifest_path: Path,
    freeze_checksums_path: Path,
    freeze_checksums: dict[str, Any],
) -> dict[str, Any]:
    """Build a reproducible protocol manifest from the frozen V4 manifest."""

    return {
        "protocol_version": PROTOCOL_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "protocol_created_no_heldout_events_selected",
        "purpose": "Untouched held-out validation protocol for frozen GeoRisk V4.",
        "strictly_prohibited_before_snapshot_freeze": [
            "CAR",
            "SCAR",
            "price returns",
            "market hit labels",
            "post-event abnormal returns",
            "ranking or mechanism tuning",
        ],
        "frozen_v4_reference": {
            "freeze_manifest_path": str(freeze_manifest_path),
            "freeze_manifest_sha256": sha256_file(freeze_manifest_path),
            "freeze_checksums_path": str(freeze_checksums_path),
            "freeze_checksums_sha256": sha256_file(freeze_checksums_path),
            "freeze_status": freeze_manifest.get("freeze_status"),
            "freeze_timestamp_utc": freeze_manifest.get("freeze_timestamp_utc"),
            "artifact_checksum_count": len(freeze_checksums.get("artifacts", {})),
        },
        "frozen_v4_specification": {
            "top_k": freeze_manifest.get("retrieval", {}).get("top_k"),
            "support_threshold": freeze_manifest.get("support_policy", {}).get("support_threshold"),
            "transmission_context_version": freeze_manifest.get("mechanism_representation", {}).get("transmission_context_version"),
            "canonical_family_version": freeze_manifest.get("mechanism_representation", {}).get("canonical_family_version"),
            "mechanism_compatibility_version": freeze_manifest.get("mechanism_representation", {}).get("mechanism_compatibility_version"),
            "asset_ranker_version": freeze_manifest.get("ranking", {}).get("asset_ranker_version"),
            "historical_context_sidecar": freeze_manifest.get("historical_representation", {}).get("sidecar_path"),
            "historical_context_coverage": freeze_manifest.get("historical_representation", {}).get("coverage"),
        },
        "event_selection_rules": {
            "source_requirements": [
                "contemporaneous source-backed geopolitical or supply-chain event",
                "clear event date T0",
                "sufficient event text for Event Analyst",
                "no exact V1/V2/V3 event overlap",
                "no exact incident-level duplicate in historical KB",
                "no CAR, price-return, or market-outcome fields used",
            ],
            "hard_filters": [
                "held_out_from_kb",
                "clear_t0",
                "clean_estimation_window",
                "low_confounding",
            ],
            "recommended_minimum_events": 12,
            "diversity_dimensions": [
                "event_type",
                "region",
                "transmission family",
                "asset universe coverage",
            ],
        },
        "freeze_sequence": [
            "Collect candidate events using only pre-outcome source facts.",
            "Screen candidates for held-out status and KB/V1/V2/V3 non-overlap.",
            "Select final V4 held-out set and seal event manifest hash.",
            "Run frozen run_v4_pipeline only; freeze prediction snapshots.",
            "Seal snapshot hashes before any CAR, price, or return inspection.",
            "Only then prepare price inputs and run CAR validation.",
        ],
        "required_future_artifacts": [
            "candidate_events.csv",
            "candidate_screening.csv",
            "accepted_events.csv",
            "excluded_events.csv",
            "v4_heldout_manifest.json",
            "prediction_snapshots/",
            "snapshot_hashes.json",
            "post_snapshot_price_input_audit.json",
        ],
        "empty_scaffold_only": True,
        "heldout_events_created": False,
        "predictions_frozen": False,
        "car_run": False,
    }


def build_initial_status() -> dict[str, Any]:
    """Return status metadata proving the scaffold has no held-out results."""

    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": "protocol_created_no_heldout_events_selected",
        "heldout_events_created": False,
        "candidate_events_populated": False,
        "accepted_events_populated": False,
        "predictions_frozen": False,
        "price_inputs_prepared": False,
        "car_run": False,
        "post_freeze_tuning_allowed": False,
    }


def validate_no_outcome_columns(columns: list[str]) -> None:
    """Reject held-out candidate files that contain market-outcome fields."""

    normalized = {str(column).strip().lower() for column in columns}
    forbidden = sorted(normalized & DISALLOWED_OUTCOME_COLUMNS)
    if forbidden:
        raise ValueError(f"outcome_columns_not_allowed:{','.join(forbidden)}")


def assert_csv_has_no_outcome_columns(path: str | Path) -> None:
    """Read one CSV header and reject forbidden market-outcome columns."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
    validate_no_outcome_columns(header)


def render_protocol_markdown(manifest: dict[str, Any]) -> str:
    """Render a human-readable V4 held-out validation protocol."""

    spec = manifest["frozen_v4_specification"]
    return "\n".join(
        [
            "# GeoRisk V4 Untouched Held-Out Validation Protocol",
            "",
            "Status: protocol scaffold only. No held-out events, predictions, prices, CAR, or hit labels have been created by this artifact.",
            "",
            "## Frozen V4 Configuration",
            "",
            f"- top_k: {spec['top_k']}",
            f"- mechanism-compatible support: enabled",
            f"- compatible support threshold: {spec['support_threshold']}",
            f"- TransmissionContext: {spec['transmission_context_version']}",
            f"- canonical family: {spec['canonical_family_version']}",
            f"- mechanism compatibility: {spec['mechanism_compatibility_version']}",
            f"- Asset Ranker: {spec['asset_ranker_version']}",
            f"- historical context sidecar: {spec['historical_context_sidecar']}",
            "",
            "## Non-Negotiable Guardrails",
            "",
            "- Do not inspect CAR, SCAR, price returns, hit labels, or post-event market outcomes before event selection and prediction snapshots are sealed.",
            "- Do not tune top_k, support threshold, canonical families, TransmissionContext schema, ranking, labels, or compatibility semantics after held-out evaluation begins.",
            "- Any held-out failure becomes a post-freeze V5 candidate issue, not a V4 tuning opportunity.",
            "",
            "## Required Sequence",
            "",
            *[
                f"{idx}. {step}"
                for idx, step in enumerate(manifest["freeze_sequence"], start=1)
            ],
            "",
            "## Event Selection Requirements",
            "",
            "- Source-backed, contemporaneous event description.",
            "- Clear event date T0.",
            "- No exact V1/V2/V3 overlap.",
            "- No exact incident-level historical KB duplicate.",
            "- Clean estimation window and low confounding for later CAR use.",
            "",
            "## Current State",
            "",
            "- heldout_events_created: false",
            "- predictions_frozen: false",
            "- car_run: false",
            "",
        ]
    ) + "\n"


def write_csv_template(path: Path, fields: list[str], overwrite: bool = False) -> Path:
    """Write an empty CSV template with a validated non-outcome header."""

    validate_no_outcome_columns(fields)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
    return path


def write_json_if_allowed(path: Path, payload: dict[str, Any], overwrite: bool = False) -> Path:
    """Write JSON while avoiding accidental overwrite."""

    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_text_if_allowed(path: Path, text: str, overwrite: bool = False) -> Path:
    """Write text while avoiding accidental overwrite."""

    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hash for a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
