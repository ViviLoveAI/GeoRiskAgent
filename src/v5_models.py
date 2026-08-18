"""Pydantic models for bounded GeoRisk V5 discovery state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.schemas import EventAnalysis, FinalReport, RetrievedCase


AnalysisStatus = Literal[
    "DISCOVERY",
    "RETRIEVAL",
    "REPAIR",
    "VERIFY",
    "FINAL",
    "ABSTAIN",
]

EvidenceDiagnosis = Literal[
    "ENOUGH_EVIDENCE",
    "NODE_GAP",
    "INSUFFICIENT_CONTEXT",
    "NO_QUALIFIED_EVIDENCE",
]

ProjectionStatus = Literal[
    "not_attempted",
    "existing_v4_context",
    "projected",
    "projection_unavailable",
]

ApplicabilityStatus = Literal[
    "not_evaluated",
    "grounded",
    "domain_association_only",
    "insufficient",
]


class CurrentContextProjection(BaseModel):
    """Audit record for current-event context projection of a repaired node."""

    node: str
    projection_attempted: bool = False
    projection_source: str | None = None
    projection_status: ProjectionStatus = "not_attempted"
    projected_current_context: dict[str, str] | None = None
    projection_cues: list[str] = Field(default_factory=list)
    applicability_status: ApplicabilityStatus = "not_evaluated"
    applicability_reason: str = ""


class AgentAction(BaseModel):
    """Auditable record of one meaningful V5 pipeline action."""

    action: str
    reason: str
    status_before: AnalysisStatus
    status_after: AnalysisStatus
    candidate_nodes_added: list[str] = Field(default_factory=list)
    source_case_ids: list[str] = Field(default_factory=list)
    support_delta: dict[str, int] = Field(default_factory=dict)
    latency_ms: int = 0
    token_usage: dict[str, int] | None = None


class NodeRepairProposal(BaseModel):
    """Traceable proposal for one bounded node discovery repair candidate."""

    proposed_node: str
    reason: str
    source_case_ids: list[str] = Field(default_factory=list)
    proposal_type: str = "historical_mechanism_expansion"
    historical_support_count: int = 0
    current_context_available: bool = False
    compatible_support_count: int = 0
    projection_attempted: bool = False
    projection_source: str | None = None
    projection_status: ProjectionStatus = "not_attempted"
    projected_current_context: dict[str, str] | None = None
    projection_cues: list[str] = Field(default_factory=list)
    applicability_status: ApplicabilityStatus = "not_evaluated"
    applicability_reason: str = ""
    specificity_recovery_evaluated: bool = False
    specificity_recovery_eligible: bool = False
    specificity_recovery_reason: str = ""
    candidate_source: str = "v5_node_repair"
    candidate_specificity: str = "unknown"
    event_default_broad: bool = False
    event_guardrail_bypassed_for_candidate: bool = False
    downstream_final_status: str = ""
    downstream_final_reason: str = ""


class AnalysisState(BaseModel):
    """Minimal shared state for GeoRisk V5 Agentic Discovery MVP."""

    event: EventAnalysis
    direct_nodes: list[str] = Field(default_factory=list)
    candidate_nodes: list[str] = Field(default_factory=list)
    historical_evidence_nodes: list[str] = Field(default_factory=list)
    current_proposed_nodes: list[str] = Field(default_factory=list)
    repair_candidate_pool: list[str] = Field(default_factory=list)
    repaired_candidate_nodes: list[str] = Field(default_factory=list)
    current_context_projections: dict[str, CurrentContextProjection] = Field(default_factory=dict)
    retrieved_cases: list[RetrievedCase] = Field(default_factory=list)
    compatible_support: dict[str, int] = Field(default_factory=dict)
    unresolved_nodes: list[str] = Field(default_factory=list)
    retrieval_attempts: int = 0
    repair_attempts: int = 0
    status: AnalysisStatus = "DISCOVERY"
    diagnosis: EvidenceDiagnosis | None = None
    repair_proposals: list[NodeRepairProposal] = Field(default_factory=list)
    trajectory: list[AgentAction] = Field(default_factory=list)


class V5AnalysisResult(BaseModel):
    """Final V5 wrapper preserving the V4 report plus V5 metadata."""

    final_report: FinalReport
    architecture_version: str
    repair_policy_version: str
    repair_enabled: bool
    state: AnalysisState
