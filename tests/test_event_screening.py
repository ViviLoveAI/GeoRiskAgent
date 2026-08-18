from src.validation.car_models import ValidationEvent
from src.validation.event_screening import (
    accepted_validation_events,
    rejected_validation_events,
    screen_validation_event,
)


def _event(**overrides) -> ValidationEvent:
    data = {
        "event_id": "placeholder_event",
        "event_date": "2024-01-01",
        "event_description": "Fake placeholder event for validation screening.",
        "held_out_from_kb": True,
        "clear_t0": True,
        "clean_estimation_window": True,
        "low_confounding": True,
        "status": "accepted",
    }
    data.update(overrides)
    return ValidationEvent(**data)


def test_screen_validation_event_accepts_clean_event():
    result = screen_validation_event(_event())

    assert result.accepted is True
    assert result.rejection_reasons == []


def test_screen_validation_event_rejects_failed_hard_filters():
    result = screen_validation_event(
        _event(
            held_out_from_kb=False,
            clear_t0=False,
            clean_estimation_window=False,
            low_confounding=False,
            status="draft",
        )
    )

    assert result.accepted is False
    assert result.rejection_reasons == [
        "held_out_from_kb_must_be_true",
        "clear_t0_must_be_true",
        "clean_estimation_window_must_be_true",
        "low_confounding_must_be_true",
        "status_must_be_accepted",
    ]


def test_screen_validation_event_rejects_non_accepted_status():
    result = screen_validation_event(_event(status="review"))

    assert result.accepted is False
    assert result.rejection_reasons == ["status_must_be_accepted"]


def test_accepted_and_rejected_validation_events_helpers():
    clean = _event(event_id="clean")
    rejected = _event(event_id="rejected", low_confounding=False)

    assert accepted_validation_events([clean, rejected]) == [clean]
    rejected_results = rejected_validation_events([clean, rejected])
    assert len(rejected_results) == 1
    assert rejected_results[0].event_id == "rejected"
    assert rejected_results[0].rejection_reasons == ["low_confounding_must_be_true"]
