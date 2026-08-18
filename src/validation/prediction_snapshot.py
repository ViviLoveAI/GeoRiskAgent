"""Freeze GeoRisk exposure predictions before CAR validation.

Snapshots prevent post-event return information from changing the predicted
exposure set used in validation. This module does not compute CAR and does not
fetch price data.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.pipeline import run_pipeline
from src.schemas import EvidenceResult, FinalReport
from src.validation.car_models import PredictedExposure, ValidationEvent
from src.validation.event_screening import accepted_validation_events


DEFAULT_MANIFEST_PATH = Path("data/validation_events.yaml")
DEFAULT_SNAPSHOT_DIR = Path("data/validation_snapshots")
SNAPSHOT_NOTE = "Frozen before observing post-event returns"
SNAPSHOT_VERSION_V1 = "v1_manifest_exposures"
SNAPSHOT_VERSION_V2 = "v2_full_pipeline"
LEGACY_SNAPSHOT_SUFFIX = "_snapshot.json"
V2_SNAPSHOT_SUFFIX = "_snapshot_v2.json"


def load_validation_events(manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> list[ValidationEvent]:
    """Load validation events from a YAML manifest."""

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load validation_events.yaml.") from exc

    path = Path(manifest_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_events = payload.get("validation_events", [])
    return [ValidationEvent.model_validate(raw_event) for raw_event in raw_events]


def load_accepted_validation_events(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> list[ValidationEvent]:
    """Load only validation events that pass hard screening filters."""

    return accepted_validation_events(load_validation_events(manifest_path))


def create_prediction_snapshot(
    event: ValidationEvent,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Create a legacy manifest-exposure snapshot for one event.

    Formal validation should use ``create_full_pipeline_prediction_snapshot``.
    This legacy helper remains for backwards compatibility with existing V1
    artifacts and lightweight smoke tests.
    """

    exposures = event.predicted_exposures or generate_predicted_exposures_placeholder(event)
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "event_id": event.event_id,
        "event_date": event.event_date,
        "event_description": event.event_description,
        "event_type": event.event_type,
        "generated_at": timestamp,
        "predicted_exposures": [
            exposure.model_dump(mode="json") for exposure in exposures
        ],
        "baseline_exposures": [
            baseline.model_dump(mode="json") for baseline in event.baseline_assets
        ],
        "snapshot_version": SNAPSHOT_VERSION_V1,
        "pipeline_mode": "manifest_exposures",
        "note": SNAPSHOT_NOTE,
    }


def create_full_pipeline_prediction_snapshot(
    event: ValidationEvent,
    generated_at: str | None = None,
    top_k: int = 3,
    event_analyzer: str = "rule",
) -> dict[str, Any]:
    """Run the full GeoRisk pipeline and freeze final EvidenceResult outputs."""

    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    try:
        report = run_pipeline(
            event.event_description,
            top_k=top_k,
            event_analyzer=event_analyzer,
        )
    except Exception as exc:
        raise RuntimeError(
            f"full_pipeline_snapshot_failed:{event.event_id}:{type(exc).__name__}: {exc}"
        ) from exc

    exposures = [
        predicted_exposure_from_evidence_result(event.event_id, result)
        for result in report.evidence_results
    ]
    if not exposures:
        raise RuntimeError(
            f"full_pipeline_snapshot_failed:{event.event_id}:no_evidence_results"
        )

    snapshot = {
        "event_id": event.event_id,
        "event_date": event.event_date,
        "event_description": event.event_description,
        "event_type": event.event_type,
        "generated_at": timestamp,
        "predicted_exposures": [
            exposure.model_dump(mode="json") for exposure in exposures
        ],
        "baseline_exposures": [
            baseline.model_dump(mode="json") for baseline in event.baseline_assets
        ],
        "retrieved_case_ids": [case.case_id for case in report.retrieved_cases],
        "pipeline_mode": "full_georisk_pipeline",
        "event_analyzer_mode": event_analyzer,
        "top_k": top_k,
        "snapshot_version": SNAPSHOT_VERSION_V2,
        "git_commit": current_git_commit(),
        "note": SNAPSHOT_NOTE,
    }
    validate_full_pipeline_snapshot(snapshot, report)
    return snapshot


def predicted_exposure_from_evidence_result(
    event_id: str,
    result: EvidenceResult,
) -> PredictedExposure:
    """Convert one final EvidenceResult into the validation exposure schema."""

    return PredictedExposure(
        event_id=event_id,
        symbol=result.ticker,
        node=result.asset.supply_chain_node or "unknown",
        asset_type=result.asset.asset_type or "unknown",
        linkage_tier=result.linkage_tier,
        linkage_rationale=result.linkage_rationale,
        transmission_order=result.transmission_order,
        confidence=result.confidence,
        evidence_label=result.evidence_level,
        supporting_case_ids=list(result.supporting_case_ids),
        supporting_case_details=list(result.supporting_case_details),
        evidence_reason=result.reason,
        evidence_rationale=result.rationale,
        relevance_score=result.relevance_score,
        priority_tier=result.priority_tier,
        rank_within_order=result.rank_within_order,
        ranking_version=result.ranking_version,
        ranking_scope=result.ranking_scope,
        ranking_key=result.ranking_key,
        supporting_case_count=result.supporting_case_count,
        ranking_components=dict(result.ranking_components),
        ranking_rationale=result.ranking_rationale,
        source="georisk",
    )


def validate_full_pipeline_snapshot(snapshot: dict[str, Any], report: FinalReport) -> None:
    """Validate that a formal snapshot faithfully serializes EvidenceResult data."""

    exposures = snapshot.get("predicted_exposures", [])
    if len(exposures) != len(report.evidence_results):
        raise RuntimeError("snapshot_integrity_failed:evidence_result_count_mismatch")

    for exposure, result in zip(exposures, report.evidence_results, strict=True):
        if exposure.get("symbol") != result.ticker:
            raise RuntimeError("snapshot_integrity_failed:symbol_mismatch")
        if exposure.get("node") != (result.asset.supply_chain_node or "unknown"):
            raise RuntimeError("snapshot_integrity_failed:node_mismatch")
        if exposure.get("evidence_label") != result.evidence_level:
            raise RuntimeError("snapshot_integrity_failed:evidence_label_mismatch")
        if exposure.get("confidence") != result.confidence:
            raise RuntimeError("snapshot_integrity_failed:confidence_mismatch")
        if exposure.get("transmission_order") != result.transmission_order:
            raise RuntimeError("snapshot_integrity_failed:transmission_order_missing")
        if exposure.get("linkage_tier") != result.linkage_tier:
            raise RuntimeError("snapshot_integrity_failed:linkage_tier_mismatch")
        if exposure.get("linkage_rationale") != result.linkage_rationale:
            raise RuntimeError("snapshot_integrity_failed:linkage_rationale_mismatch")
        if exposure.get("supporting_case_ids", []) != list(result.supporting_case_ids):
            raise RuntimeError("snapshot_integrity_failed:supporting_case_ids_mismatch")
        if exposure.get("supporting_case_details", []) != list(result.supporting_case_details):
            raise RuntimeError("snapshot_integrity_failed:supporting_case_details_mismatch")
        if exposure.get("relevance_score") != result.relevance_score:
            raise RuntimeError("snapshot_integrity_failed:relevance_score_mismatch")
        if exposure.get("priority_tier") != result.priority_tier:
            raise RuntimeError("snapshot_integrity_failed:priority_tier_mismatch")
        if exposure.get("rank_within_order") != result.rank_within_order:
            raise RuntimeError("snapshot_integrity_failed:rank_within_order_mismatch")
        if exposure.get("ranking_version") != result.ranking_version:
            raise RuntimeError("snapshot_integrity_failed:ranking_version_mismatch")
        if exposure.get("ranking_scope") != result.ranking_scope:
            raise RuntimeError("snapshot_integrity_failed:ranking_scope_mismatch")
        if exposure.get("ranking_key") != result.ranking_key:
            raise RuntimeError("snapshot_integrity_failed:ranking_key_mismatch")
        if exposure.get("supporting_case_count") != result.supporting_case_count:
            raise RuntimeError("snapshot_integrity_failed:supporting_case_count_mismatch")
        if exposure.get("ranking_components", {}) != dict(result.ranking_components):
            raise RuntimeError("snapshot_integrity_failed:ranking_components_mismatch")
        if exposure.get("ranking_rationale") != result.ranking_rationale:
            raise RuntimeError("snapshot_integrity_failed:ranking_rationale_mismatch")
        if exposure.get("evidence_label") == "inference_only" and exposure.get("confidence") != 0.35:
            raise RuntimeError("snapshot_integrity_failed:inference_confidence_mismatch")
        if exposure.get("evidence_label") != "inference_only" and exposure.get("confidence") == 0.35:
            raise RuntimeError("snapshot_integrity_failed:silent_inference_default")


def save_prediction_snapshot(
    snapshot: dict[str, Any],
    output_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    overwrite: bool = True,
) -> Path:
    """Save one snapshot without changing older snapshot versions."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_file_path(
        output_path,
        snapshot["event_id"],
        str(snapshot.get("snapshot_version") or SNAPSHOT_VERSION_V1),
    )
    if snapshot_path.exists() and not overwrite:
        raise FileExistsError(f"Snapshot already exists: {snapshot_path}")
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot_path


def freeze_prediction_snapshots(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    output_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    rebuild: bool = False,
    snapshot_version: str = SNAPSHOT_VERSION_V2,
) -> list[Path]:
    """Create frozen snapshots for all accepted validation events in a manifest."""

    snapshot_paths: list[Path] = []
    for event in load_accepted_validation_events(manifest_path):
        path = snapshot_file_path(output_dir, event.event_id, snapshot_version)
        if path.exists() and not rebuild:
            snapshot_paths.append(path)
            continue
        if snapshot_version == SNAPSHOT_VERSION_V2:
            snapshot = create_full_pipeline_prediction_snapshot(event)
        else:
            snapshot = create_prediction_snapshot(event)
        snapshot_paths.append(save_prediction_snapshot(snapshot, output_dir))
    return snapshot_paths


def generate_predicted_exposures_placeholder(event: ValidationEvent) -> list[PredictedExposure]:
    """Placeholder for future GeoRisk analyzer integration.

    TODO: Replace this with a deterministic call into the GeoRisk analyzer once
    the validation workflow defines the exact export contract.
    """

    return []


def snapshot_file_path(
    output_dir: str | Path,
    event_id: str,
    snapshot_version: str = SNAPSHOT_VERSION_V2,
) -> Path:
    """Return the versioned snapshot path for an event."""

    suffix = V2_SNAPSHOT_SUFFIX if snapshot_version == SNAPSHOT_VERSION_V2 else LEGACY_SNAPSHOT_SUFFIX
    return Path(output_dir) / f"{event_id}{suffix}"


def load_or_create_full_pipeline_snapshot(
    event: ValidationEvent,
    snapshot_dir: str | Path = DEFAULT_SNAPSHOT_DIR,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Load an existing V2 snapshot or create one from the full pipeline."""

    path = snapshot_file_path(snapshot_dir, event.event_id, SNAPSHOT_VERSION_V2)
    if path.exists() and not rebuild:
        return json.loads(path.read_text(encoding="utf-8"))
    snapshot = create_full_pipeline_prediction_snapshot(event)
    save_prediction_snapshot(snapshot, snapshot_dir)
    return snapshot


def current_git_commit() -> str | None:
    """Return the current Git commit hash when available."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None
