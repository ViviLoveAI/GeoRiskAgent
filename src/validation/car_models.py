"""Structured models for ex-post GeoRisk validation.

These models support validation workflows only. They describe held-out events,
GeoRisk-predicted exposures, and future CAR results without changing the core
GeoRisk analyzer or implying price prediction.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PredictedExposure(BaseModel):
    """An asset exposure flagged by GeoRisk for a validation event."""

    event_id: str
    symbol: str
    node: str
    asset_type: str
    linkage_tier: str | None = None
    linkage_rationale: str | None = None
    transmission_order: str | None = None
    confidence: float | None = None
    evidence_label: str | None = None
    supporting_case_ids: list[str] = Field(default_factory=list)
    supporting_case_details: list[dict[str, object]] = Field(default_factory=list)
    evidence_reason: str | None = None
    evidence_rationale: str | None = None
    relevance_score: float | None = None
    priority_tier: str | None = None
    rank_within_order: int | None = None
    ranking_version: str | None = None
    ranking_scope: str | None = None
    ranking_key: dict[str, object] | None = None
    supporting_case_count: int | None = None
    ranking_components: dict[str, object] = Field(default_factory=dict)
    ranking_rationale: str | None = None
    expected_direction: str | None = None
    source: str = "georisk"


class BaselineExposure(BaseModel):
    """A baseline asset exposure used for GeoRisk comparison only."""

    symbol: str
    node: str
    asset_type: str
    baseline_type: str | None = None
    source: str = "baseline"


class ValidationEvent(BaseModel):
    """A candidate held-out event for ex-post validation."""

    event_id: str
    event_date: str
    event_description: str
    event_type: str | None = None
    notes: str = ""
    held_out_from_kb: bool = False
    clear_t0: bool = False
    clean_estimation_window: bool = False
    low_confounding: bool = False
    status: str = "draft"
    predicted_exposures: list[PredictedExposure] = Field(default_factory=list)
    baseline_assets: list[BaselineExposure] = Field(default_factory=list)


class CARResult(BaseModel):
    """Future CAR validation result for one event-symbol pair."""

    event_id: str
    symbol: str
    car: float | None = None
    standardized_car: float | None = None
    hit: bool = False
    direction: str | None = None
    missing_data_reason: str | None = None
    supporting_notes: list[str] = Field(default_factory=list)
