import csv
import json

import pytest

from src.validation.v4_temporal_heldout import (
    BENCHMARK_VERSION,
    EXPECTED_SUPPORT_CLASSES,
    assert_temporal_heldout_ready_for_prediction,
    seal_temporal_heldout_benchmark,
)


def test_temporal_seal_uses_only_eligible_candidate_pool(tmp_path):
    paths = _fixture_files(tmp_path)

    result = seal_temporal_heldout_benchmark(**paths)

    final_events = _read_csv(tmp_path / "out" / "temporal_final_heldout_events.csv")
    assert result["selected_event_count"] == 16
    assert result["node_annotation_count"] == 32
    assert {row["event_id"] for row in final_events}.issubset(_selected_ids())
    assert result["predictions_frozen"] is False
    assert result["car_run"] is False


def test_temporal_final_set_contains_only_pre_outcome_fields(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)

    final_events = _read_csv(tmp_path / "out" / "temporal_final_heldout_events.csv")
    forbidden = {"car", "scar", "return", "hit", "price_before", "price_after"}
    assert final_events
    assert not (set(final_events[0]) & forbidden)
    assert all(row["benchmark_version"] == BENCHMARK_VERSION for row in final_events)


def test_ground_truth_taxonomy_is_frozen_and_created_before_prediction(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)

    ground_truth = _read_csv(tmp_path / "out" / "temporal_heldout_ground_truth.csv")
    labels = {row["expected_support_class"] for row in ground_truth}
    assert labels == EXPECTED_SUPPORT_CLASSES
    assert any(row["expected_support_class"] == "weak_cooccurrence_expected" for row in ground_truth)
    assert any(row["expected_support_class"] == "insufficient_context_expected" for row in ground_truth)
    assert any(row["representation_gap_observed"] == "True" for row in ground_truth)


def test_same_node_different_mechanism_can_be_weak(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)

    ground_truth = _read_csv(tmp_path / "out" / "temporal_heldout_ground_truth.csv")
    weak = [
        row
        for row in ground_truth
        if row["node"] == "fertilizer_inputs"
        and row["expected_support_class"] == "weak_cooccurrence_expected"
    ]
    assert weak


def test_manifest_and_status_mark_sealed_without_prediction_or_car(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)

    manifest = json.loads((tmp_path / "out" / "v4_temporal_heldout_manifest.json").read_text())
    status = json.loads((tmp_path / "out" / "heldout_status.json").read_text())
    assert manifest["benchmark_name"] == "V4 Temporal Generalization Held-out"
    assert manifest["benchmark_type"] == "temporal_generalization"
    assert manifest["event_year"] == 2026
    assert manifest["leakage_status"]["V4_predictions_run"] is False
    assert manifest["leakage_status"]["prices_accessed"] is False
    assert manifest["leakage_status"]["CAR_run"] is False
    assert status["heldout_events_created"] is True
    assert status["ground_truth_frozen"] is True
    assert status["predictions_frozen"] is False
    assert status["car_run"] is False


def test_prediction_readiness_requires_sealed_manifest_and_checksums(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)

    ready = assert_temporal_heldout_ready_for_prediction(
        manifest_path=tmp_path / "out" / "v4_temporal_heldout_manifest.json",
        checksums_path=tmp_path / "out" / "v4_temporal_heldout_checksums.json",
        freeze_manifest_path=paths["freeze_manifest_path"],
    )

    assert ready["ready_for_prediction"] is True
    assert ready["selected_event_count"] == 16


def test_checksums_detect_event_mutation(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)
    final_events = tmp_path / "out" / "temporal_final_heldout_events.csv"
    final_events.write_text(final_events.read_text() + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checksum_mismatch"):
        assert_temporal_heldout_ready_for_prediction(
            manifest_path=tmp_path / "out" / "v4_temporal_heldout_manifest.json",
            checksums_path=tmp_path / "out" / "v4_temporal_heldout_checksums.json",
            freeze_manifest_path=paths["freeze_manifest_path"],
        )


def test_exact_duplicate_cannot_enter_final_set(tmp_path):
    paths = _fixture_files(tmp_path, omit_selected=True)
    provisional_path = paths["provisional_accepted_path"]
    rows = _candidate_rows()
    selected = [row for row in rows if row["candidate_id"] in _selected_ids()]
    selected = selected[:-1]
    _write_csv(provisional_path, ["candidate_id"], [[row["candidate_id"]] for row in selected])

    with pytest.raises(RuntimeError, match="selected_not_eligible"):
        seal_temporal_heldout_benchmark(**paths)


def test_no_new_canonical_family_is_added_by_temporal_seal(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)
    manifest = json.loads((tmp_path / "out" / "v4_temporal_heldout_manifest.json").read_text())

    assert manifest["annotation"]["taxonomy"] == sorted(EXPECTED_SUPPORT_CLASSES)
    assert "agriculture_constraint" not in json.dumps(manifest)


def test_prices_car_and_prediction_artifacts_absent(tmp_path):
    paths = _fixture_files(tmp_path)
    seal_temporal_heldout_benchmark(**paths)

    out = tmp_path / "out"
    assert not (out / "prediction_snapshots" / "snapshot_hashes.json").exists()
    assert not (out / "car_results" / "car_pair_results.csv").exists()
    assert not (out / "prices").exists()


def _fixture_files(tmp_path, omit_selected=False):
    out = tmp_path / "out"
    out.mkdir()
    status = out / "heldout_status.json"
    status.write_text(json.dumps({"predictions_frozen": False, "car_run": False}), encoding="utf-8")
    candidates = tmp_path / "candidate_events.csv"
    rows = _candidate_rows()
    _write_csv(candidates, list(rows[0]), [[row[field] for field in rows[0]] for row in rows])
    provisional = tmp_path / "provisional.csv"
    provisional_rows = rows if not omit_selected else [row for row in rows if row["candidate_id"] not in _selected_ids()]
    _write_csv(provisional, ["candidate_id"], [[row["candidate_id"]] for row in provisional_rows])
    freeze_manifest = tmp_path / "v4_final_freeze_manifest.json"
    freeze_manifest.write_text(
        json.dumps(
            {
                "freeze_status": "V4 DEVELOPMENT FROZEN",
                "retrieval": {"top_k": 10},
                "support_policy": {"support_threshold": 2},
                "mechanism_representation": {
                    "transmission_context_version": "transmission_context_v1",
                    "canonical_family_version": "canonical_family_v1",
                    "mechanism_compatibility_version": "mechanism_compatibility_candidate_v1",
                },
            }
        ),
        encoding="utf-8",
    )
    freeze_checksums = tmp_path / "checksums.json"
    freeze_checksums.write_text(json.dumps({"artifacts": {}}), encoding="utf-8")
    return {
        "candidate_path": candidates,
        "provisional_accepted_path": provisional,
        "freeze_manifest_path": freeze_manifest,
        "freeze_checksums_path": freeze_checksums,
        "output_dir": out,
    }


def _candidate_rows():
    import csv as _csv
    from pathlib import Path

    path = Path("data/validation_v4/candidate_events.csv")
    if path.exists():
        return list(_csv.DictReader(path.open()))
    raise RuntimeError("fixture requires data/validation_v4/candidate_events.csv")


def _selected_ids():
    from src.validation.v4_temporal_heldout import SELECTED_CANDIDATE_IDS

    return set(SELECTED_CANDIDATE_IDS)


def _write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)


def _read_csv(path):
    return list(csv.DictReader(path.open()))
