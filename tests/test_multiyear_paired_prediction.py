import csv
import json
from pathlib import Path

import pytest

import src.validation.multiyear_paired_prediction as paired
from src.schemas import (
    EventAnalysis,
    FinalReport,
    RetrievedCase,
    TransmissionChain,
)


def test_pre_run_integrity_requires_sealed_benchmark_and_freezes():
    result = paired.pre_run_integrity_check()

    assert result["selected_event_count"] == 23
    assert result["node_annotation_count"] == 46
    assert result["v3_manifest_checksums_valid"] is True
    assert result["v4_manifest_checksums_valid"] is True


def test_prediction_generation_uses_same_23_events_and_does_not_read_ground_truth(tmp_path, monkeypatch):
    events_seen = []

    def fake_runner(text):
        events_seen.append(text)
        return _report()

    monkeypatch.setattr(
        paired,
        "evaluate_paired_predictions",
        lambda *args, **kwargs: {"evaluation_skipped": True},
    )
    result = paired.run_and_freeze_system_predictions(
        system="v3",
        runner=fake_runner,
        prediction_dir=tmp_path / "v3",
        overwrite=False,
        preflight={"fixture": True},
    )

    manifest = json.loads(Path(result["prediction_manifest"]).read_text())
    assert len(events_seen) == 23
    assert result["successful"] == 23
    assert manifest["ground_truth_accessed_during_generation"] is False
    assert manifest["prices_accessed"] is False
    assert manifest["CAR_run"] is False


def test_v3_v4_config_identifiers_are_frozen():
    v3 = paired.system_config("v3")
    v4 = paired.system_config("v4")

    assert v3["top_k"] == 3
    assert v3["TransmissionContext_enabled"] is False
    assert v3["mechanism_compatibility_enabled"] is False
    assert v4["top_k"] == 10
    assert v4["mechanism_compatible_support"] is True
    assert v4["support_threshold"] == 2


def test_evaluation_requires_prediction_checksums(tmp_path):
    with pytest.raises(FileNotFoundError):
        paired.evaluate_paired_predictions(
            ground_truth_path="data/validation_general/multiyear_ground_truth.csv",
            v3_node_snapshot_path=tmp_path / "v3_nodes.csv",
            v4_node_snapshot_path=tmp_path / "v4_nodes.csv",
            v3_checksums_path=tmp_path / "missing_v3.json",
            v4_checksums_path=tmp_path / "missing_v4.json",
            output_path=tmp_path / "comparison.csv",
            summary_path=tmp_path / "summary.json",
        )


def test_freeze_checksum_guard_allows_declared_post_freeze_production_file(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    production_file = src_dir / "implementation.py"
    production_file.write_text("before", encoding="utf-8")
    checksums = _checksums(tmp_path / "checksums.json", [production_file])
    production_file.write_text("after", encoding="utf-8")
    manifest = tmp_path / "post_freeze_manifest.json"
    _post_freeze_manifest(manifest, ["src/implementation.py"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paired, "POST_FREEZE_PRODUCTION_FIX_PATH", manifest)

    paired.assert_flat_or_wrapped_checksums_valid(checksums)


def test_freeze_checksum_guard_rejects_undeclared_mutation(tmp_path, monkeypatch):
    artifact = tmp_path / "data" / "validation_v4" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("before", encoding="utf-8")
    checksums = _checksums(tmp_path / "checksums.json", [artifact])
    artifact.write_text("after", encoding="utf-8")
    manifest = tmp_path / "post_freeze_manifest.json"
    _post_freeze_manifest(manifest, [])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paired, "POST_FREEZE_PRODUCTION_FIX_PATH", manifest)

    with pytest.raises(RuntimeError, match="checksum_mismatch"):
        paired.assert_flat_or_wrapped_checksums_valid(checksums)


def test_freeze_checksum_guard_rejects_declared_frozen_artifact_mutation(tmp_path, monkeypatch):
    artifact = tmp_path / "data" / "validation_v4" / "result.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("before", encoding="utf-8")
    checksums = _checksums(tmp_path / "checksums.json", [artifact])
    artifact.write_text("after", encoding="utf-8")
    manifest = tmp_path / "post_freeze_manifest.json"
    _post_freeze_manifest(manifest, ["data/validation_v4/result.json"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paired, "POST_FREEZE_PRODUCTION_FIX_PATH", manifest)

    with pytest.raises(RuntimeError, match="checksum_mismatch"):
        paired.assert_flat_or_wrapped_checksums_valid(checksums)


def test_evaluation_outputs_paired_transition_rows(tmp_path):
    truth = tmp_path / "truth.csv"
    truth.write_text(
        "\n".join(
            [
                "event_id,node,expected_support_class,representation_gap_observed",
                "event_1,node_a,compatible_support_expected,False",
                "event_1,node_b,weak_cooccurrence_expected,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    v3_nodes = tmp_path / "v3_nodes.csv"
    v4_nodes = tmp_path / "v4_nodes.csv"
    fields = "system,event_id,node,node_present,support_decision\n"
    v3_nodes.write_text(fields + "v3,event_1,node_a,True,True\nv3,event_1,node_b,True,True\n", encoding="utf-8")
    v4_nodes.write_text(fields + "v4,event_1,node_a,True,True\n", encoding="utf-8")
    v3_checksums = _checksums(tmp_path / "v3_checksums.json", [v3_nodes])
    v4_checksums = _checksums(tmp_path / "v4_checksums.json", [v4_nodes])

    summary = paired.evaluate_paired_predictions(
        ground_truth_path=truth,
        v3_node_snapshot_path=v3_nodes,
        v4_node_snapshot_path=v4_nodes,
        v3_checksums_path=v3_checksums,
        v4_checksums_path=v4_checksums,
        output_path=tmp_path / "comparison.csv",
        summary_path=tmp_path / "summary.json",
    )
    rows = list(csv.DictReader(open(tmp_path / "comparison.csv", newline="", encoding="utf-8")))

    assert len(rows) == 2
    assert summary["total_annotations"] == 2
    assert summary["prices_accessed"] is False
    assert summary["CAR_run"] is False


def test_prediction_snapshots_are_not_silently_overwritten(tmp_path):
    paired.run_and_freeze_system_predictions(
        system="v3",
        runner=lambda text: _report(),
        prediction_dir=tmp_path / "v3",
        overwrite=False,
        preflight={"fixture": True},
    )

    with pytest.raises(FileExistsError):
        paired.run_and_freeze_system_predictions(
            system="v3",
            runner=lambda text: _report(),
            prediction_dir=tmp_path / "v3",
            overwrite=False,
            preflight={"fixture": True},
        )


def _report():
    event = EventAnalysis(
        title="Fixture",
        summary="Fixture event",
        event_type="fixture",
        regions=["Global"],
        industries=["shipping"],
        supply_chain_nodes=["ports"],
        shock_direction="disruption",
        risk_factors=[],
    )
    case = RetrievedCase(
        case_id="case_1",
        title="Case",
        summary="Case summary",
        event_type="fixture",
        supply_chain_nodes=["ports"],
        transmission_chain=["ports"],
        relevance="rank=1",
    )
    chain = TransmissionChain(
        chain_steps=["disruption", "ports"],
        affected_nodes=["ports"],
        node_supporting_case_ids={"ports": ["case_1", "case_2"]},
        node_evidence_levels={"ports": "event_node"},
        supporting_case_ids=["case_1"],
        rationale="fixture",
    )
    return FinalReport(
        event=event,
        retrieved_cases=[case],
        transmission_chain=chain,
        evidence_results=[],
        summary="fixture",
        event_summary="fixture",
        disclaimer="not investment advice",
    )


def _checksums(path, artifacts):
    payload = {"artifacts": {str(artifact): paired.sha256_file(artifact) for artifact in artifacts}}
    Path(path).write_text(json.dumps(payload), encoding="utf-8")
    return path


def _post_freeze_manifest(path, declared_files):
    payload = {
        "manifest_id": "v4_post_freeze_production_fix_manifest",
        "methodology_version": "V4",
        "production_version": "V4.1",
        "frozen_evaluation_artifacts_regenerated": False,
        "frozen_evaluation_metrics_changed": False,
        "downstream_methodology_changed": False,
        "retrieval_config_changed": False,
        "support_policy_changed": False,
        "ranking_algorithm_changed": False,
        "evidence_grading_semantics_changed": False,
        "historical_kb_changed": False,
        "asset_mapping_semantics_changed": False,
        "declared_post_freeze_production_files": declared_files,
    }
    Path(path).write_text(json.dumps(payload), encoding="utf-8")
    return path
