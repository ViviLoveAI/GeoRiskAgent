"""Schemas and constants for CSV-first CAR validation.

The CAR layer is an ex-post evaluation tool. It checks whether assets flagged
by GeoRisk showed unusual movement around held-out geopolitical events. It does
not predict prices and does not provide investment advice.
"""

from __future__ import annotations

from dataclasses import dataclass


HELDOUT_EVENT_COLUMNS = ["event_id", "event_date", "event_description", "notes"]
PREDICTED_ASSET_COLUMNS = [
    "event_id",
    "symbol",
    "node",
    "asset_type",
    "confidence",
    "evidence_label",
]
BASELINE_ASSET_COLUMNS = [
    "event_id",
    "symbol",
    "node",
    "asset_type",
    "baseline_type",
]
PRICE_COLUMNS = ["date", "symbol", "adj_close"]
REPORT_COLUMNS = [
    "event_id",
    "event_date",
    "t0_date",
    "group",
    "symbol",
    "node",
    "asset_type",
    "confidence",
    "evidence_label",
    "baseline_type",
    "car",
    "estimation_std_abnormal_return",
    "standardized_car",
    "hit",
    "direction",
    "missing_data_reason",
]


@dataclass(frozen=True)
class CarWindowConfig:
    """Trading-day windows and hit threshold for CAR validation."""

    event_window_start: int = -1
    event_window_end: int = 1
    estimation_window_start: int = -130
    estimation_window_end: int = -10
    hit_threshold: float = 1.96
