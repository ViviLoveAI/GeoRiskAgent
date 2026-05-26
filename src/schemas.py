"""Pydantic schemas for GeoRisk Transmission Analyzer.

These models describe events, assets, historical cases, and analysis outputs.
They are intentionally lightweight placeholders for the initial project
structure.
"""

from pydantic import BaseModel, Field


class GeoRiskEvent(BaseModel):
    """A geopolitical risk event to analyze."""

    title: str = Field(..., description="Short event title.")
    description: str = Field(..., description="Plain-language event summary.")
    regions: list[str] = Field(default_factory=list)


class CandidateAsset(BaseModel):
    """An asset candidate loaded from data/asset_mapping.csv."""

    asset_id: str
    name: str
    category: str | None = None
    region: str | None = None
    supply_chain_node: str | None = None
    sector: str | None = None
    ticker: str | None = None
    asset_name: str | None = None
    asset_type: str | None = None
    notes: str | None = None
    mapping_rationale: str | None = None


class HistoricalCase(BaseModel):
    """A historical case loaded from data/historical_cases.json."""

    case_id: str
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)


class TransmissionAnalysis(BaseModel):
    """Structured analysis result.

    This output should explain possible transmission channels. It must not
    forecast stock prices or provide investment advice.
    """

    event: GeoRiskEvent
    candidate_assets: list[CandidateAsset] = Field(default_factory=list)
    related_cases: list[HistoricalCase] = Field(default_factory=list)
    transmission_channels: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EventAnalysis(BaseModel):
    """Structured interpretation of a news item as a geopolitical risk event."""

    title: str
    summary: str
    event_type: str
    regions: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    supply_chain_nodes: list[str] = Field(default_factory=list)
    shock_direction: str
    risk_factors: list[str] = Field(default_factory=list)


class RetrievedCase(BaseModel):
    """Historical case retrieved from data/historical_cases.json."""

    case_id: str
    title: str
    summary: str
    event_type: str | None = None
    transmission_chain: list[str] = Field(default_factory=list)
    relevance: str | None = None


class TransmissionChain(BaseModel):
    """Narrative chain describing possible risk transmission paths."""

    chain_steps: list[str] = Field(default_factory=list)
    affected_nodes: list[str] = Field(default_factory=list)
    supporting_case_ids: list[str] = Field(default_factory=list)
    rationale: str
    channels: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EvidenceResult(BaseModel):
    """Evidence assessment for a mapped candidate asset."""

    asset: CandidateAsset
    evidence_grade: str
    rationale: str
    supporting_case_ids: list[str] = Field(default_factory=list)
    ticker: str
    asset_name: str
    evidence_level: str
    confidence: float
    reason: str


class FinalReport(BaseModel):
    """Final analytical report.

    The report explains possible transmission channels and evidence quality. It
    must not predict stock prices or provide investment advice.
    """

    event: EventAnalysis
    retrieved_cases: list[RetrievedCase] = Field(default_factory=list)
    transmission_chain: TransmissionChain
    evidence_results: list[EvidenceResult] = Field(default_factory=list)
    summary: str
    event_summary: str
    retrieved_case_summaries: list[dict[str, str]] = Field(default_factory=list)
    secondary_asset_watchlist: dict[str, list[dict[str, object]]] = Field(default_factory=dict)
    risk_notes: list[str] = Field(default_factory=list)
    disclaimer: str
    limitations: list[str] = Field(default_factory=list)
