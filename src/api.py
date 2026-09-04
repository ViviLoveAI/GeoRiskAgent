"""FastAPI production backend for GeoRisk Transmission Analyzer."""

from __future__ import annotations

import logging
from datetime import date
from datetime import datetime

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.config import (
    INTERACTIVE_EVENT_ANALYZER,
    LLM_EVENT_ANALYST_MAX_RETRIES,
    LLM_EVENT_ANALYST_TIMEOUT_SECONDS,
)
from src.health_checks import (
    DependencyHealth,
    llm_configuration_health,
    probe_llm_endpoint,
    validate_asset_mapping,
    validate_historical_cases,
)
from src.input_normalizer import normalize_event_input
from src.orchestration.langgraph_v5 import run_v5_langgraph
from src.schemas import FinalReport
from src.v4_config import (
    POST_FREEZE_FIX_MANIFEST,
    POST_FREEZE_FIXES_ENABLED,
    V4_CONFIG,
)
from src.v5_config import (
    METHODOLOGY_VERSION,
    PRODUCTION_VERSION,
    V5_RECOVERY_APPLICABILITY_CONFIG,
)
from src.vector_store_health import assert_vector_store_ready, validate_vector_store


logger = logging.getLogger(__name__)

app = FastAPI(
    title="GeoRisk Transmission Analyzer API",
    description=(
        "Production service boundary for geopolitical risk exposure discovery. "
        "This service does not predict stock prices or provide investment advice."
    ),
)


class AnalyzeRequest(BaseModel):
    """Production request body for risk transmission analysis."""

    model_config = ConfigDict(extra="forbid")

    event: str | None = Field(
        default=None,
        description="Required event name or short geopolitical event phrase.",
    )
    event_year: int | None = Field(
        default=None,
        description="Optional event year. No exact date is inferred.",
    )
    context: str | None = Field(
        default=None,
        description="Optional user-supplied context for ambiguous events.",
    )
    description: str | None = Field(
        default=None,
        description="Backward-compatible event description.",
    )
    news_text: str | None = Field(
        default=None,
        description="Backward-compatible alias for description.",
    )
    title: str | None = Field(default=None, description="Optional event title.")
    event_date: date | None = Field(default=None, description="Optional event date.")

    @field_validator("event_year")
    @classmethod
    def validate_event_year(cls, value: int | None) -> int | None:
        """Validate optional user-supplied year without inventing a date."""

        if value is None:
            return None
        current_year = datetime.now().year
        if value < 1900 or value > current_year + 2:
            raise ValueError("event_year must be between 1900 and two years from now.")
        return value

    @model_validator(mode="after")
    def validate_event_text(self) -> "AnalyzeRequest":
        """Require one non-empty event input field."""

        if not self.event_text.strip():
            raise ValueError("event input must not be empty.")
        return self

    @property
    def event_text(self) -> str:
        """Return the canonical text sent to the GeoRisk pipeline."""

        return build_analysis_input(self)

    @property
    def display_title(self) -> str | None:
        """Return the best user-facing title for the report."""

        return self.title or self.event or self.description or self.news_text


class HealthVectorStore(BaseModel):
    """Vector-store health details safe for deployment checks."""

    status: str
    collection: str
    documents: int | None = None
    message: str | None = None


class HealthComponent(BaseModel):
    """One required or optional dependency health result."""

    status: str
    required: bool
    healthy: bool
    records: int | None = None
    message: str | None = None


class HealthResponse(BaseModel):
    """API health response."""

    status: str
    vector_store: HealthVectorStore
    ready: bool
    components: dict[str, HealthComponent]


class VersionConfiguration(BaseModel):
    """Safe production configuration metadata."""

    top_k: int
    support_threshold: int
    mechanism_compatible: bool
    event_analyzer: str
    llm_timeout_seconds: float
    llm_max_retries: int
    transmission_context_version: str
    canonical_family_version: str
    mechanism_compatibility_version: str
    architecture_version: str
    verification_boundary: str
    max_repair_attempts: int
    max_new_candidate_nodes: int
    node_repair_enabled: bool
    specificity_recovery_enabled: bool
    current_event_applicability_gate_enabled: bool


class VersionResponse(BaseModel):
    """Runtime version response."""

    system: str
    production_version: str
    methodology_version: str
    version: str
    runtime: str
    post_freeze_fixes: bool
    post_freeze_fix_manifest: str | None = None
    configuration: VersionConfiguration


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return detailed readiness with a non-networked optional LLM status."""

    return _health_response(active_llm_probe=False)


@app.get("/health/live")
def health_live() -> dict[str, str]:
    """Return process liveness without touching external dependencies."""

    return {"status": "alive"}


@app.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    """Return readiness based only on dependencies required for deterministic mode."""

    return _health_response(active_llm_probe=False)


@app.get("/health/deep", response_model=HealthResponse)
def health_deep() -> HealthResponse:
    """Run an explicit optional LLM endpoint probe plus all required checks."""

    return _health_response(active_llm_probe=True)


def _health_response(*, active_llm_probe: bool) -> HealthResponse:
    """Build a component-level health response and enforce required readiness."""

    vector_health = validate_vector_store()
    vector_status = "ready" if vector_health.healthy else "unavailable"
    historical_cases = validate_historical_cases()
    asset_mapping = validate_asset_mapping()
    llm = probe_llm_endpoint() if active_llm_probe else llm_configuration_health()
    dependencies = [historical_cases, asset_mapping, llm]
    required_ready = vector_health.healthy and all(
        dependency.healthy for dependency in dependencies if dependency.required
    )
    optional_degraded = any(
        not dependency.healthy for dependency in dependencies if not dependency.required
    )
    overall_status = (
        "unhealthy"
        if not required_ready
        else "degraded"
        if optional_degraded
        else "healthy"
    )
    response = HealthResponse(
        status=overall_status,
        ready=required_ready,
        vector_store=HealthVectorStore(
            status=vector_status,
            collection=vector_health.collection_name,
            documents=vector_health.collection_count,
            message=None if vector_health.healthy else vector_health.message,
        ),
        components={
            "vector_store": HealthComponent(
                status=vector_status,
                required=True,
                healthy=vector_health.healthy,
                records=vector_health.collection_count,
                message=None if vector_health.healthy else vector_health.message,
            ),
            **{
                dependency.name: _health_component(dependency)
                for dependency in dependencies
            },
        },
    )
    if not required_ready:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=response.model_dump())
    return response


def _health_component(dependency: DependencyHealth) -> HealthComponent:
    """Convert an internal dependency result to the public response schema."""

    return HealthComponent(
        status=dependency.status,
        required=dependency.required,
        healthy=dependency.healthy,
        records=dependency.records,
        message=dependency.message,
    )


@app.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    """Return safe runtime metadata for configuration drift checks."""

    return VersionResponse(
        system="GeoRisk",
        production_version=PRODUCTION_VERSION,
        methodology_version=METHODOLOGY_VERSION,
        version=PRODUCTION_VERSION,
        runtime="V5 LangGraph bounded recovery with Frozen V4 verification boundary",
        post_freeze_fixes=POST_FREEZE_FIXES_ENABLED,
        post_freeze_fix_manifest=POST_FREEZE_FIX_MANIFEST,
        configuration=VersionConfiguration(
            top_k=V4_CONFIG.retrieval_top_k,
            support_threshold=V4_CONFIG.compatible_support_threshold,
            mechanism_compatible=V4_CONFIG.use_mechanism_compatible_support,
            event_analyzer=INTERACTIVE_EVENT_ANALYZER,
            llm_timeout_seconds=LLM_EVENT_ANALYST_TIMEOUT_SECONDS,
            llm_max_retries=LLM_EVENT_ANALYST_MAX_RETRIES,
            transmission_context_version=V4_CONFIG.transmission_context_version,
            canonical_family_version=V4_CONFIG.canonical_family_version,
            mechanism_compatibility_version=V4_CONFIG.mechanism_compatibility_version,
            architecture_version=V5_RECOVERY_APPLICABILITY_CONFIG.architecture_version,
            verification_boundary="Frozen V4 / V4.1 deterministic verification",
            max_repair_attempts=V5_RECOVERY_APPLICABILITY_CONFIG.max_repair_attempts,
            max_new_candidate_nodes=V5_RECOVERY_APPLICABILITY_CONFIG.max_new_candidate_nodes,
            node_repair_enabled=V5_RECOVERY_APPLICABILITY_CONFIG.enable_node_repair,
            specificity_recovery_enabled=(
                V5_RECOVERY_APPLICABILITY_CONFIG.enable_specificity_recovery
            ),
            current_event_applicability_gate_enabled=(
                V5_RECOVERY_APPLICABILITY_CONFIG.enable_current_event_applicability_gate
            ),
        ),
    )


@app.post("/analyze", response_model=FinalReport)
def analyze(request: AnalyzeRequest) -> FinalReport:
    """Run the production GeoRisk V5 LangGraph path for a geopolitical event."""

    try:
        assert_vector_store_ready()
        normalized_input = normalize_event_input(request.event_text)
        logger.info(
            "GeoRisk API analysis starting: runtime=V5_LangGraph "
            "verification_boundary=Frozen_V4 top_k=%s "
            "mechanism_compatible_support=%s event_analyzer=%s input_language=%s "
            "max_repair_attempts=%s max_new_candidate_nodes=%s",
            V4_CONFIG.retrieval_top_k,
            V4_CONFIG.use_mechanism_compatible_support,
            INTERACTIVE_EVENT_ANALYZER,
            normalized_input.detected_language,
            V5_RECOVERY_APPLICABILITY_CONFIG.max_repair_attempts,
            V5_RECOVERY_APPLICABILITY_CONFIG.max_new_candidate_nodes,
        )
        if normalized_input.normalization_error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Non-English input normalization is temporarily unavailable. "
                    "Please retry later or submit the event in English."
                ),
            )
        v5_result = run_v5_langgraph(
            normalized_input.analysis_text,
            event_analyzer=INTERACTIVE_EVENT_ANALYZER,
            config=V5_RECOVERY_APPLICABILITY_CONFIG,
        )
        report = v5_result.final_report
        return report.model_copy(
            update={
                "input_title": request.display_title,
                "input_event_date": request.event_date.isoformat() if request.event_date else None,
                "input_event_year": request.event_year,
                "input_context": clean_optional_text(request.context),
                "original_event_text": normalized_input.original_text,
                "normalized_event_text": normalized_input.analysis_text,
                "input_language": normalized_input.detected_language,
                "input_normalization_applied": normalized_input.normalization_applied,
                "input_normalization_error": normalized_input.normalization_error,
            }
        )
    except HTTPException:
        raise
    except ValueError as exc:
        logger.info("GeoRisk API rejected invalid input: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="event must contain a geopolitical risk event.",
        ) from exc
    except Exception as exc:
        logger.exception("GeoRisk API analysis failed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GeoRisk analysis is temporarily unavailable.",
        ) from exc


def build_analysis_input(request: AnalyzeRequest) -> str:
    """Build analysis text only from fields supplied by the user."""

    primary = first_non_empty(request.event, request.description, request.news_text)
    parts = [primary]
    if request.event_year is not None:
        parts.append(f"Year: {request.event_year}")
    context = clean_optional_text(request.context)
    if context:
        parts.append(f"Context: {context}")
    return "\n".join(part for part in parts if part).strip()


def first_non_empty(*values: str | None) -> str:
    """Return the first non-empty string from a list of optional values."""

    for value in values:
        cleaned = clean_optional_text(value)
        if cleaned:
            return cleaned
    return ""


def clean_optional_text(value: str | None) -> str | None:
    """Return stripped text or None."""

    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
