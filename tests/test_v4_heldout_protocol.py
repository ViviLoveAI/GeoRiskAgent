import csv
import json

import pytest

from src.validation.v4_heldout_protocol import (
    CANDIDATE_EVENT_FIELDS,
    PROTOCOL_VERSION,
    assert_csv_has_no_outcome_columns,
    assert_freeze_manifest_ready,
    create_v4_heldout_protocol,
    validate_no_outcome_columns,
)


def test_freeze_manifest_must_match_frozen_v4_spec(tmp_path):
    manifest = _freeze_manifest(tmp_path)

    loaded = assert_freeze_manifest_ready(manifest)

    assert loaded["freeze_status"] == "V4 DEVELOPMENT FROZEN"


def test_freeze_manifest_rejects_wrong_top_k(tmp_path):
    manifest = _freeze_manifest(tmp_path, top_k=5)

    with pytest.raises(RuntimeError, match="top_k"):
        assert_freeze_manifest_ready(manifest)


def test_protocol_scaffold_creates_no_heldout_events_or_results(tmp_path):
    manifest = _freeze_manifest(tmp_path)
    checksums = _checksums(tmp_path)
    output_dir = tmp_path / "validation_v4"

    result = create_v4_heldout_protocol(
        output_dir=output_dir,
        freeze_manifest_path=manifest,
        freeze_checksums_path=checksums,
    )

    protocol = json.loads((output_dir / "v4_heldout_protocol_manifest.json").read_text())
    status = json.loads((output_dir / "heldout_status.json").read_text())
    assert result["heldout_events_created"] is False
    assert result["predictions_frozen"] is False
    assert result["car_run"] is False
    assert protocol["protocol_version"] == PROTOCOL_VERSION
    assert protocol["empty_scaffold_only"] is True
    assert status["candidate_events_populated"] is False
    assert status["car_run"] is False
    assert not (output_dir / "accepted_events.csv").exists()
    assert not (output_dir / "prediction_snapshots" / "snapshot_hashes.json").exists()


def test_candidate_template_contains_only_ex_ante_fields(tmp_path):
    manifest = _freeze_manifest(tmp_path)
    checksums = _checksums(tmp_path)
    output_dir = tmp_path / "validation_v4"

    create_v4_heldout_protocol(output_dir, manifest, checksums)

    template = output_dir / "templates" / "candidate_events_template.csv"
    with template.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert header == CANDIDATE_EVENT_FIELDS
    assert_csv_has_no_outcome_columns(template)


def test_outcome_columns_are_rejected():
    with pytest.raises(ValueError, match="car"):
        validate_no_outcome_columns(["event_id", "event_date", "CAR"])

    with pytest.raises(ValueError, match="standardized_car"):
        validate_no_outcome_columns(["event_id", "standardized_car"])


def test_protocol_references_freeze_hashes(tmp_path):
    manifest = _freeze_manifest(tmp_path)
    checksums = _checksums(tmp_path)
    output_dir = tmp_path / "validation_v4"

    create_v4_heldout_protocol(output_dir, manifest, checksums)

    protocol = json.loads((output_dir / "v4_heldout_protocol_manifest.json").read_text())
    frozen_reference = protocol["frozen_v4_reference"]
    assert frozen_reference["freeze_manifest_path"] == str(manifest)
    assert frozen_reference["freeze_checksums_path"] == str(checksums)
    assert len(frozen_reference["freeze_manifest_sha256"]) == 64
    assert len(frozen_reference["freeze_checksums_sha256"]) == 64
    assert frozen_reference["artifact_checksum_count"] == 1


def test_protocol_refuses_to_overwrite_without_explicit_flag(tmp_path):
    manifest = _freeze_manifest(tmp_path)
    checksums = _checksums(tmp_path)
    output_dir = tmp_path / "validation_v4"
    create_v4_heldout_protocol(output_dir, manifest, checksums)

    with pytest.raises(FileExistsError):
        create_v4_heldout_protocol(output_dir, manifest, checksums)

    result = create_v4_heldout_protocol(output_dir, manifest, checksums, overwrite=True)
    assert result["heldout_events_created"] is False


def _freeze_manifest(tmp_path, top_k=10):
    path = tmp_path / "v4_final_freeze_manifest.json"
    payload = {
        "freeze_status": "V4 DEVELOPMENT FROZEN",
        "freeze_timestamp_utc": "2026-08-11T21:00:09+00:00",
        "retrieval": {
            "top_k": top_k,
            "embedding_model": "all-MiniLM-L6-v2",
            "vector_store": "ChromaDB PersistentClient",
        },
        "support_policy": {
            "support_threshold": 2,
        },
        "mechanism_representation": {
            "transmission_context_version": "transmission_context_v1",
            "canonical_family_version": "canonical_family_v1",
            "mechanism_compatibility_version": "mechanism_compatibility_candidate_v1",
        },
        "ranking": {
            "asset_ranker_version": "ranking_v1",
        },
        "historical_representation": {
            "coverage": 0.847458,
            "sidecar_path": "data/transmission_context_v1.json",
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _checksums(tmp_path):
    path = tmp_path / "v4_freeze_checksums.json"
    path.write_text(
        json.dumps({"artifacts": {"src/v4_config.py": "abc123"}}, indent=2),
        encoding="utf-8",
    )
    return path
