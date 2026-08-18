import json

import pytest

from src.schemas import (
    CandidateAsset,
    EventAnalysis,
    EvidenceResult,
    FinalReport,
    RetrievedCase,
    TransmissionChain,
)
from src.validation.car_models import ValidationEvent
from src.validation.prediction_snapshot import (
    SNAPSHOT_NOTE,
    SNAPSHOT_VERSION_V2,
    create_full_pipeline_prediction_snapshot,
    create_prediction_snapshot,
    freeze_prediction_snapshots,
    load_accepted_validation_events,
    save_prediction_snapshot,
)


def _manifest_text() -> str:
    return """
validation_events:
  - event_id: accepted_event
    event_date: "2024-01-02"
    event_description: "Fake accepted event."
    notes: "Fake placeholder."
    held_out_from_kb: true
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: accepted
    predicted_exposures:
      - event_id: accepted_event
        symbol: FAKE
        node: placeholder_node
        asset_type: placeholder_asset
        confidence: 0.5
        evidence_label: sector_proxy
        source: manual
  - event_id: rejected_event
    event_date: "2024-01-03"
    event_description: "Fake rejected event."
    held_out_from_kb: false
    clear_t0: true
    clean_estimation_window: true
    low_confounding: true
    status: draft
    predicted_exposures:
      - event_id: rejected_event
        symbol: NOPE
        node: placeholder_node
        asset_type: placeholder_asset
"""


def test_load_accepted_validation_events_from_manifest(tmp_path):
    manifest = tmp_path / "validation_events.yaml"
    manifest.write_text(_manifest_text(), encoding="utf-8")

    events = load_accepted_validation_events(manifest)

    assert [event.event_id for event in events] == ["accepted_event"]
    assert events[0].predicted_exposures[0].symbol == "FAKE"


def test_create_prediction_snapshot_includes_required_fields():
    event = ValidationEvent(
        event_id="accepted_event",
        event_date="2024-01-02",
        event_description="Fake accepted event.",
        held_out_from_kb=True,
        clear_t0=True,
        clean_estimation_window=True,
        low_confounding=True,
        status="accepted",
    )

    snapshot = create_prediction_snapshot(
        event,
        generated_at="2024-01-02T00:00:00+00:00",
    )

    assert snapshot == {
        "event_id": "accepted_event",
        "event_date": "2024-01-02",
        "event_description": "Fake accepted event.",
        "event_type": None,
        "generated_at": "2024-01-02T00:00:00+00:00",
        "predicted_exposures": [],
        "baseline_exposures": [],
        "snapshot_version": "v1_manifest_exposures",
        "pipeline_mode": "manifest_exposures",
        "note": SNAPSHOT_NOTE,
    }


def test_freeze_prediction_snapshots_writes_only_accepted_events(tmp_path, monkeypatch):
    manifest = tmp_path / "validation_events.yaml"
    output_dir = tmp_path / "snapshots"
    manifest.write_text(_manifest_text(), encoding="utf-8")
    monkeypatch.setattr(
        "src.validation.prediction_snapshot.run_pipeline",
        lambda *args, **kwargs: _report_with_results(
            [_evidence_result(symbol="FAKE")]
        ),
    )

    paths = freeze_prediction_snapshots(manifest, output_dir)

    assert len(paths) == 1
    assert paths[0].name == "accepted_event_snapshot_v2.json"
    assert not (output_dir / "rejected_event_snapshot.json").exists()

    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["event_id"] == "accepted_event"
    assert payload["note"] == SNAPSHOT_NOTE
    assert payload["predicted_exposures"][0]["symbol"] == "FAKE"


def test_full_pipeline_snapshot_preserves_evidence_agent_output(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.validation.prediction_snapshot.run_pipeline",
        lambda *args, **kwargs: _report_with_results(
            [
                _evidence_result(
                    symbol="AAA",
                    node="semiconductor_equipment",
                    evidence_level="sector_proxy",
                    confidence=0.64,
                    transmission_order="first_order",
                    supporting_case_ids=["case_sector"],
                ),
                _evidence_result(
                    symbol="BBB",
                    node="oil_shipping",
                    evidence_level="historical_supported",
                    confidence=0.82,
                    transmission_order="second_order",
                    supporting_case_ids=["case_historical"],
                ),
            ]
        ),
    )
    event = _accepted_event()

    snapshot = create_full_pipeline_prediction_snapshot(
        event,
        generated_at="2024-01-02T00:00:00+00:00",
    )
    path = save_prediction_snapshot(snapshot, tmp_path)
    loaded = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "accepted_event_snapshot_v2.json"
    assert loaded["snapshot_version"] == SNAPSHOT_VERSION_V2
    assert loaded["pipeline_mode"] == "full_georisk_pipeline"
    assert set(loaded["retrieved_case_ids"]) == {"case_sector", "case_historical"}

    by_symbol = {row["symbol"]: row for row in loaded["predicted_exposures"]}
    assert by_symbol["AAA"]["evidence_label"] == "sector_proxy"
    assert by_symbol["AAA"]["confidence"] == 0.64
    assert by_symbol["AAA"]["transmission_order"] == "first_order"
    assert by_symbol["AAA"]["linkage_tier"] == "direct_exposure"
    assert by_symbol["AAA"]["linkage_rationale"] == "AAA linkage rationale"
    assert by_symbol["AAA"]["supporting_case_ids"] == ["case_sector"]
    assert by_symbol["AAA"]["supporting_case_details"] == [
        {"case_id": "case_sector", "retrieval_rank": 1}
    ]
    assert by_symbol["AAA"]["relevance_score"] == 71.5
    assert by_symbol["AAA"]["priority_tier"] == "medium_priority"
    assert by_symbol["AAA"]["rank_within_order"] == 1
    assert by_symbol["AAA"]["ranking_version"] == "ranking_v1"
    assert by_symbol["AAA"]["ranking_scope"] == "ranked_second_order"
    assert by_symbol["AAA"]["ranking_key"] == {"evidence_rank": 2}
    assert by_symbol["AAA"]["supporting_case_count"] == 1
    assert by_symbol["AAA"]["ranking_components"] == {"evidence_strength": 0.65}
    assert by_symbol["AAA"]["ranking_rationale"] == "AAA ranking rationale"
    assert by_symbol["AAA"]["evidence_reason"] == "sector_proxy reason"

    assert by_symbol["BBB"]["evidence_label"] == "historical_supported"
    assert by_symbol["BBB"]["confidence"] == 0.82
    assert by_symbol["BBB"]["transmission_order"] == "second_order"
    assert by_symbol["BBB"]["linkage_tier"] == "direct_exposure"
    assert by_symbol["BBB"]["linkage_rationale"] == "BBB linkage rationale"
    assert by_symbol["BBB"]["supporting_case_ids"] == ["case_historical"]


def test_full_pipeline_failure_does_not_create_inference_only_snapshot(monkeypatch):
    monkeypatch.setattr(
        "src.validation.prediction_snapshot.run_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("retrieval unavailable")),
    )

    with pytest.raises(RuntimeError, match="full_pipeline_snapshot_failed"):
        create_full_pipeline_prediction_snapshot(_accepted_event())


def test_second_order_exposures_are_not_dropped(monkeypatch):
    monkeypatch.setattr(
        "src.validation.prediction_snapshot.run_pipeline",
        lambda *args, **kwargs: _report_with_results(
            [
                _evidence_result(
                    symbol="SECOND",
                    node="marine_insurance",
                    evidence_level="sector_proxy",
                    confidence=0.64,
                    transmission_order="second_order",
                    supporting_case_ids=["case_shipping"],
                )
            ]
        ),
    )

    snapshot = create_full_pipeline_prediction_snapshot(_accepted_event())

    assert len(snapshot["predicted_exposures"]) == 1
    assert snapshot["predicted_exposures"][0]["symbol"] == "SECOND"
    assert snapshot["predicted_exposures"][0]["transmission_order"] == "second_order"


def test_existing_v2_snapshot_is_not_overwritten(tmp_path, monkeypatch):
    manifest = tmp_path / "validation_events.yaml"
    output_dir = tmp_path / "snapshots"
    output_dir.mkdir()
    manifest.write_text(_manifest_text(), encoding="utf-8")
    existing = output_dir / "accepted_event_snapshot_v2.json"
    existing.write_text('{"event_id": "accepted_event", "marker": "old"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "src.validation.prediction_snapshot.run_pipeline",
        lambda *args, **kwargs: _report_with_results(
            [_evidence_result(symbol="NEW")]
        ),
    )

    paths = freeze_prediction_snapshots(manifest, output_dir)

    assert paths == [existing]
    assert json.loads(existing.read_text(encoding="utf-8"))["marker"] == "old"


def _accepted_event():
    return ValidationEvent(
        event_id="accepted_event",
        event_date="2024-01-02",
        event_description="Fake accepted event.",
        held_out_from_kb=True,
        clear_t0=True,
        clean_estimation_window=True,
        low_confounding=True,
        status="accepted",
    )


def _report_with_results(results):
    return FinalReport(
        event=EventAnalysis(
            title="Event",
            summary="Summary",
            event_type="test",
            shock_direction="negative",
        ),
        retrieved_cases=[
            RetrievedCase(case_id=case_id, title=case_id, summary="Case summary")
            for case_id in sorted({
                case_id
                for result in results
                for case_id in result.supporting_case_ids
            })
        ],
        transmission_chain=TransmissionChain(rationale="Chain"),
        evidence_results=results,
        summary="Summary",
        event_summary="Summary",
        disclaimer="No investment advice.",
    )


def _evidence_result(
    symbol="AAA",
    node="semiconductor_equipment",
    evidence_level="sector_proxy",
    confidence=0.64,
    transmission_order="first_order",
    supporting_case_ids=None,
):
    supporting_case_ids = supporting_case_ids or ["case_sector"]
    asset = CandidateAsset(
        asset_id=symbol,
        name=symbol,
        ticker=symbol,
        asset_name=symbol,
        asset_type="equity",
        supply_chain_node=node,
        linkage_tier="direct_exposure",
        linkage_rationale=f"{symbol} linkage rationale",
    )
    return EvidenceResult(
        asset=asset,
        evidence_grade=evidence_level,
        rationale=f"{evidence_level} rationale",
        supporting_case_ids=supporting_case_ids,
        supporting_case_details=[
            {"case_id": supporting_case_ids[0], "retrieval_rank": 1}
        ],
        ticker=symbol,
        asset_name=symbol,
        evidence_level=evidence_level,
        confidence=confidence,
        reason=f"{evidence_level} reason",
        transmission_order=transmission_order,
        linkage_tier=asset.linkage_tier,
        linkage_rationale=asset.linkage_rationale,
        relevance_score=71.5,
        priority_tier="medium_priority",
        rank_within_order=1,
        ranking_version="ranking_v1",
        ranking_scope="ranked_second_order",
        ranking_key={"evidence_rank": 2},
        supporting_case_count=1,
        ranking_components={"evidence_strength": 0.65},
        ranking_rationale=f"{symbol} ranking rationale",
    )
