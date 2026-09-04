"""Structured, file-backed observability for GeoRisk analysis runs.

The module deliberately keeps telemetry local and dependency-light. It records
candidate gate decisions and one JSON summary per analysis run without logging
raw event text, prompts, model output, credentials, or authorization headers.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.config import PROJECT_ROOT


OutcomeStatus = Literal[
    "RANKED",
    "RANKING_ABSTAIN",
    "FULL_ABSTAIN",
    "OPERATIONAL_FAILURE",
]


class GateDecision(BaseModel):
    """One auditable candidate decision at a deterministic or LLM gate."""

    candidate_type: str
    candidate_id: str
    gate: str
    accepted: bool
    reason_code: str
    support_count: int | None = None
    threshold: int | None = None


class FunnelMetrics(BaseModel):
    """Stage-level input/output counts for one analysis run."""

    direct_node_count: int = 0
    retrieved_case_count: int = 0
    raw_candidate_node_count: int = 0
    mechanism_compatible_node_count: int = 0
    support_qualified_node_count: int = 0
    affected_node_count: int = 0
    mapped_asset_count: int = 0
    ranked_second_order_count: int = 0
    first_order_reference_count: int = 0
    rejected_decision_count: int = 0


class ExecutionMetadata(BaseModel):
    """Safe execution metadata returned with an analytical report."""

    run_id: str
    requested_event_analyzer: str
    effective_event_analyzer: str
    degraded: bool = False
    degradation_reason: str | None = None
    total_latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    llm_latency_share_pct: float = 0.0
    phase_latency_ms: dict[str, float] = Field(default_factory=dict)
    token_usage: dict[str, int] | None = None
    outcome_status: OutcomeStatus
    funnel: FunnelMetrics = Field(default_factory=FunnelMetrics)
    gate_decisions: list[GateDecision] = Field(default_factory=list)


@dataclass
class RunTelemetry:
    """Mutable request-local collector hidden behind a ContextVar."""

    run_id: str
    gate_decisions: list[GateDecision] = field(default_factory=list)


_current_telemetry: ContextVar[RunTelemetry | None] = ContextVar(
    "georisk_run_telemetry",
    default=None,
)
_LOGGER_NAME = "georisk.runtime"
_LOG_PATH = PROJECT_ROOT / "logs" / "georisk-runtime.jsonl"


class JsonFormatter(logging.Formatter):
    """Format telemetry records as one compact JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "event_payload", None)
        if not isinstance(payload, dict):
            payload = {"message": record.getMessage()}
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                **payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def new_run_id() -> str:
    """Return a collision-resistant identifier for one analysis run."""

    return str(uuid4())


@contextmanager
def analysis_run(run_id: str | None = None) -> Iterator[RunTelemetry]:
    """Bind a telemetry collector to the current sync or async context."""

    collector = RunTelemetry(run_id=run_id or new_run_id())
    token = _current_telemetry.set(collector)
    try:
        yield collector
    finally:
        _current_telemetry.reset(token)


def current_telemetry() -> RunTelemetry | None:
    """Return the request-local telemetry collector when one is active."""

    return _current_telemetry.get()


def record_gate_decision(
    *,
    candidate_type: str,
    candidate_id: str,
    gate: str,
    accepted: bool,
    reason_code: str,
    support_count: int | None = None,
    threshold: int | None = None,
) -> None:
    """Append a safe gate decision to the active run, if any."""

    collector = current_telemetry()
    if collector is None:
        return
    collector.gate_decisions.append(
        GateDecision(
            candidate_type=candidate_type,
            candidate_id=candidate_id,
            gate=gate,
            accepted=accepted,
            reason_code=reason_code,
            support_count=support_count,
            threshold=threshold,
        )
    )


def emit_run_record(metadata: ExecutionMetadata, *, total_latency_ms: float) -> Path:
    """Write one structured run summary to the rotating local JSONL file."""

    logger = _runtime_logger()
    logger.info(
        "analysis_run_completed",
        extra={
            "event_payload": {
                "schema_version": "1.0",
                "event": "analysis_run_completed",
                "run_id": metadata.run_id,
                "requested_event_analyzer": metadata.requested_event_analyzer,
                "effective_event_analyzer": metadata.effective_event_analyzer,
                "degraded": metadata.degraded,
                "degradation_reason": metadata.degradation_reason,
                "outcome_status": metadata.outcome_status,
                "total_latency_ms": round(total_latency_ms, 3),
                "llm_latency_ms": round(metadata.llm_latency_ms, 3),
                "llm_latency_share_pct": round(metadata.llm_latency_share_pct, 3),
                "phase_latency_ms": metadata.phase_latency_ms,
                "token_usage": metadata.token_usage,
                "funnel": metadata.funnel.model_dump(),
                "gate_decisions": [
                    decision.model_dump() for decision in metadata.gate_decisions
                ],
            }
        },
    )
    return _LOG_PATH


def _runtime_logger() -> logging.Logger:
    """Return an idempotently configured local JSONL logger."""

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            _LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger
