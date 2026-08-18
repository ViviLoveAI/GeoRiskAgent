"""Hard-filter screening for CAR validation event candidates."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.validation.car_models import ValidationEvent


HARD_FILTER_FIELDS = [
    "held_out_from_kb",
    "clear_t0",
    "clean_estimation_window",
    "low_confounding",
]
ACCEPTED_STATUS = "accepted"


@dataclass(frozen=True)
class ScreeningResult:
    """Result of applying validation-event hard filters."""

    event_id: str
    accepted: bool
    rejection_reasons: list[str] = field(default_factory=list)


def screen_validation_event(event: ValidationEvent) -> ScreeningResult:
    """Apply hard filters to one validation event candidate."""

    reasons: list[str] = []
    for field_name in HARD_FILTER_FIELDS:
        if not getattr(event, field_name):
            reasons.append(f"{field_name}_must_be_true")

    if event.status != ACCEPTED_STATUS:
        reasons.append("status_must_be_accepted")

    return ScreeningResult(
        event_id=event.event_id,
        accepted=not reasons,
        rejection_reasons=reasons,
    )


def accepted_validation_events(events: list[ValidationEvent]) -> list[ValidationEvent]:
    """Return only events that pass all hard filters."""

    return [
        event
        for event in events
        if screen_validation_event(event).accepted
    ]


def rejected_validation_events(events: list[ValidationEvent]) -> list[ScreeningResult]:
    """Return screening results for events that fail at least one hard filter."""

    return [
        result
        for result in (screen_validation_event(event) for event in events)
        if not result.accepted
    ]
