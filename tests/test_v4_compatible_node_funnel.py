import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.validation.v4_compatible_node_funnel import build_compatible_node_funnel


def test_compatible_funnel_uses_only_21_compatible_pairs(tmp_path, monkeypatch):
    _forbid_prediction_or_retrieval(monkeypatch)
    summary = build_compatible_node_funnel(
        output_path=tmp_path / "funnel.csv",
        summary_path=tmp_path / "summary.json",
        post_retrieval_loss_path=tmp_path / "loss.csv",
        node_discovery_miss_path=tmp_path / "miss.csv",
    )
    rows = _rows(tmp_path / "funnel.csv")

    assert summary["compatible_ground_truth_total"] == 21
    assert len(rows) == 21
    truth_rows = _rows("data/validation_v4/temporal_heldout_ground_truth.csv")
    compatible_keys = {
        (row["event_id"], row["node"])
        for row in truth_rows
        if row["expected_support_class"] == "compatible_support_expected"
    }
    assert {(row["event_id"], row["expected_node"]) for row in rows} == compatible_keys


def test_attempt_002_checksum_required_before_funnel(tmp_path, monkeypatch):
    _forbid_prediction_or_retrieval(monkeypatch)
    bad_checksums = tmp_path / "bad_checksums.json"
    bad_checksums.write_text(
        json.dumps(
            {
                "artifacts": {
                    "data/validation_v4/predictions/attempt_002/v4_temporal_prediction_snapshot.csv": "bad"
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="prediction_checksum_mismatch"):
        build_compatible_node_funnel(
            prediction_checksums_path=bad_checksums,
            output_path=tmp_path / "funnel.csv",
            summary_path=tmp_path / "summary.json",
            post_retrieval_loss_path=tmp_path / "loss.csv",
            node_discovery_miss_path=tmp_path / "miss.csv",
        )


def test_funnel_reconciles_final_retained_count_and_unique_stage(tmp_path, monkeypatch):
    _forbid_prediction_or_retrieval(monkeypatch)
    summary = build_compatible_node_funnel(
        output_path=tmp_path / "funnel.csv",
        summary_path=tmp_path / "summary.json",
        post_retrieval_loss_path=tmp_path / "loss.csv",
        node_discovery_miss_path=tmp_path / "miss.csv",
    )
    rows = _rows(tmp_path / "funnel.csv")

    assert summary["final_retained"] == 3
    assert sum(row["final_node_retained"] == "True" for row in rows) == 3
    assert all(row["first_failure_stage"] for row in rows)
    assert sum(summary["first_failure_stage_counts"].values()) == 21


def test_funnel_preserves_frozen_attempt_artifacts(tmp_path, monkeypatch):
    _forbid_prediction_or_retrieval(monkeypatch)
    watched = [
        Path("data/validation_v4/predictions/attempt_002/v4_temporal_raw_predictions.json"),
        Path("data/validation_v4/predictions/attempt_002/v4_temporal_prediction_snapshot.csv"),
        Path("data/validation_v4/predictions/attempt_002/v4_temporal_asset_snapshot.csv"),
        Path("data/validation_v4/temporal_heldout_ground_truth.csv"),
        Path("data/transmission_context_v1.json"),
    ]
    before = {path: _sha(path) for path in watched}

    build_compatible_node_funnel(
        output_path=tmp_path / "funnel.csv",
        summary_path=tmp_path / "summary.json",
        post_retrieval_loss_path=tmp_path / "loss.csv",
        node_discovery_miss_path=tmp_path / "miss.csv",
    )

    assert {path: _sha(path) for path in watched} == before


def _forbid_prediction_or_retrieval(monkeypatch):
    import src.pipeline
    import src.vector_store

    monkeypatch.setattr(
        src.pipeline,
        "run_v4_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pipeline rerun forbidden")),
    )
    monkeypatch.setattr(
        src.vector_store,
        "query_cases",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("retrieval rerun forbidden")),
    )


def _rows(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
