import csv
import json
import sys

import pytest

from src.validation.v4_heldout_candidate_screening import (
    CandidateRecord,
    ReferenceEvent,
    detect_outcome_leakage,
    screen_candidate_record,
    screen_v4_heldout_candidates,
)


def test_eligible_independent_event_passes_without_prediction(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "src.pipeline", _ExplodingPipeline())
    candidates = tmp_path / "candidate_events.csv"
    _write_candidates(candidates, [_candidate("independent_event")])
    freeze_manifest = _freeze_manifest(tmp_path)
    status = tmp_path / "heldout_status.json"
    status.write_text(
        json.dumps(
            {
                "predictions_frozen": False,
                "car_run": False,
            }
        ),
        encoding="utf-8",
    )

    summary = screen_v4_heldout_candidates(
        candidate_path=candidates,
        output_path=tmp_path / "screening.csv",
        summary_path=tmp_path / "summary.json",
        provisional_accepted_path=tmp_path / "provisional.csv",
        status_path=status,
        kb_path=_kb(tmp_path, []),
        v3_accepted_path=_csv(tmp_path / "v3.csv", ["event_id", "event_date", "event_type"], []),
        validation_events_path=tmp_path / "missing.yaml",
        development_dir=tmp_path / "dev",
        freeze_manifest_path=freeze_manifest,
    )

    updated_status = json.loads(status.read_text())
    assert summary["candidate_count"] == 1
    assert summary["eligible_count"] == 1
    assert summary["v4_prediction_run"] is False
    assert summary["car_run"] is False
    assert updated_status["candidate_pool_created"] is True
    assert updated_status["predictions_frozen"] is False
    assert updated_status["car_run"] is False


def test_forbidden_outcome_field_is_rejected_at_load(tmp_path):
    candidates = tmp_path / "candidate_events.csv"
    _csv(candidates, ["candidate_id", "event_date", "CAR"], [["x", "2025-01-02", "1.2"]])

    with pytest.raises(ValueError, match="outcome_columns_not_allowed"):
        screen_v4_heldout_candidates(
            candidate_path=candidates,
            output_path=tmp_path / "screening.csv",
            summary_path=tmp_path / "summary.json",
            provisional_accepted_path=tmp_path / "provisional.csv",
            status_path=tmp_path / "status.json",
            kb_path=_kb(tmp_path, []),
            v3_accepted_path=tmp_path / "missing.csv",
            validation_events_path=tmp_path / "missing.yaml",
            development_dir=tmp_path / "dev",
            freeze_manifest_path=_freeze_manifest(tmp_path),
        )


def test_obvious_outcome_leakage_text_is_rejected():
    candidate = CandidateRecord(
        {
            **_candidate("leaky_event"),
            "notes": "Shares later rose after the event, with a strong market reaction.",
        }
    )

    result = screen_candidate_record(candidate, [], [], [])

    assert detect_outcome_leakage(candidate.raw) is True
    assert result.eligibility_status == "reject_outcome_leakage"


def test_exact_kb_overlap_is_rejected():
    candidate = CandidateRecord(_candidate("kb_duplicate", event_date="2025-02-01"))
    kb = [
        ReferenceEvent(
            event_id="kb_duplicate",
            event_date="2025-02-01",
            event_name=candidate.event_name,
            event_text=candidate.event_text,
            event_type=candidate.event_type,
            source_group="historical_kb",
        )
    ]

    result = screen_candidate_record(candidate, kb, [], [])

    assert result.eligibility_status == "reject_exact_kb_overlap"
    assert result.kb_overlap_status == "exact_event_overlap"


def test_development_overlap_is_rejected():
    candidate = CandidateRecord(_candidate("dev_overlap"))
    dev = [
        ReferenceEvent(
            event_id="dev_overlap",
            event_date=candidate.event_date,
            event_name=candidate.event_name,
            event_text=candidate.event_text,
            event_type=candidate.event_type,
            source_group="development",
        )
    ]

    result = screen_candidate_record(candidate, [], dev, [])

    assert result.eligibility_status == "reject_development_overlap"


def test_prior_validation_overlap_is_rejected():
    candidate = CandidateRecord(_candidate("prior_overlap"))
    prior = [
        ReferenceEvent(
            event_id="prior_overlap",
            event_date=candidate.event_date,
            event_name=candidate.event_name,
            event_text=candidate.event_text,
            event_type=candidate.event_type,
            source_group="prior_validation",
        )
    ]

    result = screen_candidate_record(candidate, [], [], prior)

    assert result.eligibility_status == "reject_prior_validation_overlap"


def test_thematic_similarity_without_duplicate_does_not_reject():
    candidate = CandidateRecord(_candidate("new_export_control", event_type="export controls"))
    kb = [
        ReferenceEvent(
            event_id="old_export_control",
            event_date="2020-01-01",
            event_name="Different export control case in another country",
            event_text="A different export control event affected another technology sector and occurred years earlier.",
            event_type="export controls",
            source_group="historical_kb",
        )
    ]

    result = screen_candidate_record(candidate, kb, [], [])

    assert result.eligibility_status == "eligible"
    assert result.kb_overlap_status == "same_event_family_but_independent"


def test_unclear_t0_and_insufficient_source_cannot_be_accepted():
    unclear_t0 = CandidateRecord({**_candidate("unclear_t0"), "t0_date": ""})
    no_source = CandidateRecord({**_candidate("no_source"), "primary_source": ""})

    assert screen_candidate_record(unclear_t0, [], [], []).eligibility_status == "reject_unclear_t0"
    assert screen_candidate_record(no_source, [], [], []).eligibility_status == "reject_insufficient_sources"


def test_missing_candidate_file_creates_empty_pool_artifacts(tmp_path):
    summary = screen_v4_heldout_candidates(
        candidate_path=tmp_path / "candidate_events.csv",
        output_path=tmp_path / "screening.csv",
        summary_path=tmp_path / "summary.json",
        provisional_accepted_path=tmp_path / "provisional.csv",
        status_path=tmp_path / "status.json",
        kb_path=_kb(tmp_path, []),
        v3_accepted_path=tmp_path / "missing.csv",
        validation_events_path=tmp_path / "missing.yaml",
        development_dir=tmp_path / "dev",
        freeze_manifest_path=_freeze_manifest(tmp_path),
    )

    assert summary["candidate_count"] == 0
    assert summary["candidate_pool_created"] is False
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["heldout_events_created"] is False
    assert status["predictions_frozen"] is False
    assert status["car_run"] is False


def _candidate(candidate_id, event_date="2025-03-04", event_type="shipping disruption"):
    return {
        "candidate_id": candidate_id,
        "event_name": "Official authority announces a new source backed trade disruption",
        "event_date": event_date,
        "t0_date": event_date,
        "short_description": (
            "Official authorities announced a new trade restriction that disrupted "
            "a defined supply chain route for industrial goods."
        ),
        "primary_source": "https://example.com/source",
        "secondary_source": "Reuters",
        "source_date": event_date,
        "event_type_if_preoutcome_observable": event_type,
        "regions": "Europe",
        "countries": "Exampleland",
        "first_order_shock_description": "Official trade restriction announcement.",
        "selection_rationale": "Source-backed event with clear announcement date.",
        "notes": "",
    }


def _write_candidates(path, rows):
    fields = list(rows[0].keys()) if rows else ["candidate_id", "event_date"]
    return _csv(path, fields, [[row.get(field, "") for field in fields] for row in rows])


def _csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)
    return path


def _kb(tmp_path, cases):
    path = tmp_path / "historical_cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


def _freeze_manifest(tmp_path):
    path = tmp_path / "v4_final_freeze_manifest.json"
    path.write_text(
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
    return path


class _ExplodingPipeline:
    def __getattr__(self, name):
        raise AssertionError(f"screening must not access pipeline.{name}")
