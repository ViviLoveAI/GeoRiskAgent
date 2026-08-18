import json

import pytest

from src.validation.prediction_snapshot import create_prediction_snapshot
from src.validation.car_calculator import MarketModelConfig
from src.validation.validation_set_builder import (
    build_validation_set,
    find_kb_overlap,
    screen_candidate,
    select_diverse_events,
    CandidateScreen,
)


@pytest.fixture(autouse=True)
def stub_full_pipeline_snapshot_for_builder_tests(monkeypatch):
    """Keep builder tests focused on selection, not the retrieval stack."""

    def fake_snapshot(event, generated_at=None, top_k=3, event_analyzer="rule"):
        snapshot = create_prediction_snapshot(event, generated_at=generated_at)
        snapshot["snapshot_version"] = "v2_full_pipeline"
        snapshot["pipeline_mode"] = "full_georisk_pipeline"
        snapshot["event_analyzer_mode"] = event_analyzer
        snapshot["retrieved_case_ids"] = ["case_fixture"]
        return snapshot

    monkeypatch.setattr(
        "src.validation.validation_set_builder.create_full_pipeline_prediction_snapshot",
        fake_snapshot,
    )


def test_excludes_incident_already_represented_in_kb(monkeypatch):
    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        lambda candidate: [_exposure(candidate["event_id"])],
    )
    candidate = {
        "event_id": "suez_duplicate",
        "event_date": "2021-03-23",
        "headline": "Ever Given blocks Suez Canal",
        "event_text": "The Ever Given container ship grounded in the Suez Canal and blocked traffic between Asia and Europe.",
        "event_type": "shipping chokepoint disruption",
        "entities": ["Ever Given", "Suez Canal"],
    }
    kb = [
        {
            "event_id": "case_2021_suez_blockage",
            "date": "2021-03-23",
            "event_name": "Suez Canal blockage by Ever Given",
            "event_type": "shipping chokepoint disruption",
            "regions": ["Middle East"],
            "countries": ["Egypt"],
            "summary": "The container ship Ever Given grounded in the Suez Canal.",
            "retrieval_text": "Ever Given Suez Canal container shipping blockage",
        }
    ]

    result = screen_candidate(candidate, kb, MarketModelConfig())

    assert result.accepted is False
    assert "incident_level_overlap_with_kb" in result.rejection_reasons


def test_allows_different_incident_from_same_broad_category(monkeypatch):
    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        lambda candidate: [_exposure(candidate["event_id"])],
    )
    candidate = {
        "event_id": "panama_canal_drought",
        "event_date": "2024-01-17",
        "headline": "Panama Canal drought restrictions disrupt shipping",
        "event_text": "Panama Canal transit restrictions caused by drought disrupted shipping schedules and freight routes for container vessels.",
        "event_type": "shipping chokepoint disruption",
        "entities": ["Panama Canal"],
    }
    kb = [
        {
            "event_id": "case_2021_suez_blockage",
            "date": "2021-03-23",
            "event_name": "Suez Canal blockage by Ever Given",
            "event_type": "shipping chokepoint disruption",
            "regions": ["Middle East"],
            "countries": ["Egypt"],
            "summary": "The container ship Ever Given grounded in the Suez Canal.",
            "retrieval_text": "Ever Given Suez Canal container shipping blockage",
        }
    ]

    result = screen_candidate(candidate, kb, MarketModelConfig())

    assert result.accepted is True
    assert result.rejection_reasons == []


def test_invalid_missing_date_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        lambda candidate: [_exposure(candidate["event_id"])],
    )
    candidate = {
        "event_id": "missing_date",
        "event_date": "",
        "headline": "Geopolitical event without date",
        "event_text": "A geopolitical event had enough text but no usable event date for validation.",
        "event_type": "trade disruption",
    }

    result = screen_candidate(candidate, [], MarketModelConfig())

    assert result.accepted is False
    assert "missing_or_invalid_event_date" in result.rejection_reasons


def test_prediction_generation_failure_is_audited_not_raised(monkeypatch):
    def fail(candidate):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        fail,
    )
    candidate = _candidate("prediction_failure", "2024-01-05", "shipping")

    result = screen_candidate(candidate, [], MarketModelConfig())

    assert result.accepted is False
    assert "prediction_generation_failed:RuntimeError" in result.rejection_reasons
    assert "no_mapped_candidate_exposure" in result.rejection_reasons


def test_deterministic_selection_prefers_event_type_diversity():
    screens = [
        _screen("b_shipping", "shipping", "2024-01-02"),
        _screen("a_shipping", "shipping", "2024-01-01"),
        _screen("c_controls", "export_controls", "2024-01-03"),
    ]

    selected = select_diverse_events(screens, max_events=2, seed=123)

    assert [screen.candidate["event_id"] for screen in selected] == [
        "c_controls",
        "a_shipping",
    ]


def test_existing_frozen_manifest_is_preserved_without_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        lambda candidate: [_exposure(candidate["event_id"])],
    )
    manifest = tmp_path / "validation_events.yaml"
    candidates = tmp_path / "candidates.json"
    kb = tmp_path / "kb.json"
    selection_dir = tmp_path / "selection"
    manifest.write_text(_manifest("existing_event", "OLD"), encoding="utf-8")
    _write_candidates(candidates, [_candidate("new_event", "2024-01-05", "shipping")])
    kb.write_text("[]\n", encoding="utf-8")

    build_validation_set(
        candidates,
        kb,
        manifest,
        selection_dir,
        snapshot_dir=tmp_path / "snapshots",
        max_events=2,
    )

    text = manifest.read_text(encoding="utf-8")
    assert "existing_event" in text
    assert "symbol: OLD" in text
    assert "new_event" in text


def test_rebuild_replaces_existing_manifest_when_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        lambda candidate: [_exposure(candidate["event_id"])],
    )
    manifest = tmp_path / "validation_events.yaml"
    candidates = tmp_path / "candidates.json"
    kb = tmp_path / "kb.json"
    selection_dir = tmp_path / "selection"
    manifest.write_text(_manifest("existing_event", "OLD"), encoding="utf-8")
    _write_candidates(candidates, [_candidate("new_event", "2024-01-05", "shipping")])
    kb.write_text("[]\n", encoding="utf-8")

    build_validation_set(
        candidates,
        kb,
        manifest,
        selection_dir,
        snapshot_dir=tmp_path / "snapshots",
        max_events=1,
        rebuild=True,
    )

    text = manifest.read_text(encoding="utf-8")
    assert "existing_event" not in text
    assert "new_event" in text


def test_builder_does_not_depend_on_car_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        lambda candidate: [_exposure(candidate["event_id"])],
    )
    manifest = tmp_path / "validation_events.yaml"
    candidates = tmp_path / "candidates.json"
    kb = tmp_path / "kb.json"
    selection_dir = tmp_path / "selection"
    car_dir = tmp_path / "data" / "car_results"
    car_dir.mkdir(parents=True)
    (car_dir / "car_summary.json").write_text('{"georisk_flagged_hit_rate": 1.0}\n')
    _write_candidates(candidates, [_candidate("new_event", "2024-01-05", "shipping")])
    kb.write_text("[]\n", encoding="utf-8")

    result = build_validation_set(
        candidates,
        kb,
        manifest,
        selection_dir,
        snapshot_dir=tmp_path / "snapshots",
        max_events=1,
    )

    metadata = json.loads((selection_dir / "selection_metadata.json").read_text())
    assert result["selected_event_ids"] == ["new_event"]
    assert metadata["selection_rules"]["car_outputs_read"] is False
    assert metadata["selection_rules"]["outcome_data_used"] is False


def test_audit_artifacts_are_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.validation.validation_set_builder.generate_prediction_exposures",
        lambda candidate: [_exposure(candidate["event_id"])],
    )
    manifest = tmp_path / "validation_events.yaml"
    candidates = tmp_path / "candidates.json"
    kb = tmp_path / "kb.json"
    selection_dir = tmp_path / "selection"
    _write_candidates(candidates, [_candidate("new_event", "2024-01-05", "shipping")])
    kb.write_text("[]\n", encoding="utf-8")

    build_validation_set(
        candidates,
        kb,
        manifest,
        selection_dir,
        snapshot_dir=tmp_path / "snapshots",
        max_events=1,
    )

    assert (selection_dir / "candidate_screening.csv").exists()
    assert (selection_dir / "accepted_events.json").exists()
    assert (selection_dir / "rejected_events.json").exists()
    assert (selection_dir / "kb_overlap_report.json").exists()
    assert (selection_dir / "selection_metadata.json").exists()
    assert (selection_dir / "final_validation_audit.md").exists()
    assert (tmp_path / "snapshots" / "new_event_snapshot_v2.json").exists()

    manifest_text = manifest.read_text(encoding="utf-8")
    assert "baseline_assets:" in manifest_text
    assert "symbol: QQQ" in manifest_text
    audit_text = (selection_dir / "final_validation_audit.md").read_text(encoding="utf-8")
    assert "Baseline Construction" in audit_text
    assert "new_event" in audit_text


def test_overlap_report_contains_closest_case_evidence():
    report = find_kb_overlap(
        {
            "event_id": "event",
            "event_date": "2024-01-10",
            "headline": "Panama Canal drought restrictions",
            "event_text": "Panama Canal drought restrictions limited vessel transits.",
            "event_type": "shipping chokepoint disruption",
            "entities": ["Panama Canal"],
        },
        [
            {
                "event_id": "case",
                "date": "2024-01-09",
                "event_name": "Panama Canal drought restrictions",
                "event_type": "shipping chokepoint disruption",
                "summary": "Panama Canal drought restrictions limited ships.",
                "countries": ["Panama"],
            }
        ],
    )

    assert report["closest_cases"][0]["case_id"] == "case"
    assert "score" in report["closest_cases"][0]


def _candidate(event_id, date, event_type):
    return {
        "event_id": event_id,
        "event_date": date,
        "headline": "Shipping disruption affects freight routes",
        "event_text": "A geopolitical shipping disruption affected freight routes, logistics networks, and maritime supply-chain planning for carriers.",
        "event_type": event_type,
    }


def _screen(event_id, event_type, date):
    return CandidateScreen(
        candidate=_candidate(event_id, date, event_type),
        accepted=True,
        rejection_reasons=[],
        prediction_exposures=[_exposure(event_id)],
        overlap_report={"closest_cases": []},
    )


def _exposure(event_id):
    return {
        "event_id": event_id,
        "symbol": "AAA",
        "node": "container_shipping",
        "asset_type": "equity",
        "transmission_order": "first_order",
        "confidence": 0.64,
        "evidence_label": "sector_proxy",
        "supporting_case_ids": ["case_fixture"],
        "evidence_reason": "Fixture support.",
        "source": "georisk",
    }


def _write_candidates(path, candidates):
    path.write_text(json.dumps({"candidates": candidates}) + "\n", encoding="utf-8")


def _manifest(event_id, symbol):
    return f"""
validation_events:
  - event_id: {event_id}
    event_date: "2024-01-04"
    event_description: "Existing frozen event text with enough detail."
    event_type: shipping
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: {event_id}
        symbol: {symbol}
        node: container_shipping
        asset_type: equity
        confidence: 0.64
        evidence_label: sector_proxy
        source: georisk
"""
