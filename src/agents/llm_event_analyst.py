"""Optional LLM-backed event analyst with strict validation and fallback.

The rule-based event analyst remains the default and fallback path. This module
accepts an LLM-generated EventAnalysis candidate only when it is valid,
vocabulary-bound, grounded in the source text, and free of investment advice or
price prediction language.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from contextvars import ContextVar
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field

from src.agents.event_analyst import DEFAULT_EVENT_TYPE, EVENT_RULES, analyze_event
from src.config import (
    ASSET_MAPPING_PATH,
    LLM_EVENT_ANALYST_MAX_RETRIES,
    LLM_EVENT_ANALYST_MODEL,
    LLM_EVENT_ANALYST_TIMEOUT_SECONDS,
    USE_LLM_EVENT_ANALYST,
)
from src import nodes
from src.observability import record_gate_decision
from src.schemas import EventAnalysis


ADVICE_OR_PRICE_LANGUAGE = [
    "buy",
    "sell",
    "hold",
    "trade recommendation",
    "investment advice",
    "price target",
    "price prediction",
    "will rise",
    "will fall",
    "guaranteed return",
    "outperform",
    "underperform",
]

EXTRA_LLM_EVENT_TYPES = {
    "financial_sanctions_payment_disruption",
    "port_labor_logistics_disruption",
    "aerospace_supply_chain_sanctions",
}

_last_analysis_trace: ContextVar[dict[str, object] | None] = ContextVar(
    "llm_event_analysis_trace",
    default=None,
)


class LLMEventAnalysisCandidate(BaseModel):
    """LLM candidate payload before conversion to EventAnalysis."""

    title: str
    summary: str
    event_type: str
    regions: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    supply_chain_nodes: list[str] = Field(default_factory=list)
    shock_direction: str
    risk_factors: list[str] = Field(default_factory=list)
    supporting_phrases: dict[str, list[str]] = Field(default_factory=dict)


def analyze_event_with_llm(news_text: str) -> EventAnalysis:
    """Analyze a news item with an optional LLM and safe rule-based fallback."""

    if not news_text.strip():
        raise ValueError("news_text must not be empty.")

    _log_runtime_status()
    _last_analysis_trace.set({
        "openai_api_key_detected": bool(os.getenv("OPENAI_API_KEY")),
        "use_llm_event_analyst": USE_LLM_EVENT_ANALYST,
        "model": LLM_EVENT_ANALYST_MODEL,
        "api_call_attempted": False,
        "fallback_occurred": False,
        "fallback_reason": None,
        "llm_latency_ms": 0.0,
        "token_usage": None,
        "supporting_phrases": {},
        "effective_event_analyzer": "llm",
        "degradation_reason": None,
    })
    api_call_attempted = False
    try:
        api_call_attempted = True
        _update_trace(api_call_attempted=True)
        _log("OpenAI API call attempted: yes")
        llm_start = perf_counter()
        try:
            raw_response = _call_llm(news_text)
        finally:
            _update_trace(
                llm_latency_ms=max(0.0, (perf_counter() - llm_start) * 1000.0)
            )
        payload = _parse_json_object(raw_response)
        _normalize_supporting_phrases(payload)
        candidate = LLMEventAnalysisCandidate.model_validate(payload)
        event = EventAnalysis.model_validate(candidate.model_dump(exclude={"supporting_phrases"}))
        _validate_vocabularies(event)
        _validate_no_tickers(event, news_text)
        _validate_no_advice_or_price_language(payload)
        _validate_grounding(news_text, candidate.supporting_phrases)
        _update_trace(supporting_phrases=candidate.supporting_phrases)
        record_gate_decision(
            candidate_type="event_analysis",
            candidate_id="llm_event_analysis",
            gate="llm_validation",
            accepted=True,
            reason_code="LLM_ACCEPTED",
        )
        _log("Fallback to rule-based analyzer: no")
        return event
    except Exception as exc:
        if not api_call_attempted:
            _log("OpenAI API call attempted: no")
        reason_code = _classify_failure(exc)
        _log("Fallback to rule-based analyzer: yes")
        _log(f"Fallback reason: {reason_code}")
        fallback_event = analyze_event(news_text)
        _update_trace(
            fallback_occurred=True,
            fallback_reason=reason_code,
            fallback_exception_type=type(exc).__name__,
            degradation_reason=reason_code,
            effective_event_analyzer="rule",
            supporting_phrases={"rule_based_keywords": fallback_event.risk_factors},
        )
        record_gate_decision(
            candidate_type="event_analysis",
            candidate_id="llm_event_analysis",
            gate="llm_validation",
            accepted=False,
            reason_code=reason_code,
        )
        return fallback_event


def get_last_analysis_trace() -> dict[str, object]:
    """Return request-local observability metadata for the latest LLM analysis."""

    return dict(_last_analysis_trace.get() or {})


def _update_trace(**updates: object) -> None:
    """Replace the request-local trace without mutating shared defaults."""

    trace = dict(_last_analysis_trace.get() or {})
    trace.update(updates)
    _last_analysis_trace.set(trace)


def _log_runtime_status() -> None:
    """Print LLM analyzer runtime configuration for observability."""

    _log(f"OPENAI_API_KEY detected: {'yes' if os.getenv('OPENAI_API_KEY') else 'no'}")
    _log(f"USE_LLM_EVENT_ANALYST: {USE_LLM_EVENT_ANALYST}")
    _log(f"LLM event analyst model: {LLM_EVENT_ANALYST_MODEL}")


def _log(message: str) -> None:
    """Write LLM analyzer status to stderr without affecting JSON output."""

    print(f"[llm_event_analyst] {message}", file=sys.stderr)


def _call_llm(news_text: str) -> str:
    """Call the configured LLM and return raw text content."""

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is not installed.") from exc

    client = OpenAI(
        timeout=LLM_EVENT_ANALYST_TIMEOUT_SECONDS,
        max_retries=LLM_EVENT_ANALYST_MAX_RETRIES,
    )
    response = client.chat.completions.create(
        model=LLM_EVENT_ANALYST_MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": _system_prompt(),
            },
            {
                "role": "user",
                "content": f"News text:\n{news_text}",
            },
        ],
    )
    _update_trace(token_usage=_token_usage(response.usage))
    content = response.choices[0].message.content
    if not content:
        raise ValueError("LLM returned empty content.")
    return content


def _classify_failure(exc: Exception) -> str:
    """Map SDK and validation failures to stable, non-sensitive reason codes."""

    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timed out" in message:
        return "LLM_TIMEOUT"
    if "authentication" in name or "permission" in name or "api key" in message:
        return "LLM_AUTH_ERROR"
    if "connection" in name:
        return "LLM_CONNECTION_ERROR"
    if "ground" in message or "supporting_phrases" in message:
        return "LLM_GROUNDING_REJECTED"
    if any(term in message for term in ADVICE_OR_PRICE_LANGUAGE):
        return "LLM_POLICY_REJECTED"
    return "LLM_INVALID_OUTPUT"


def _token_usage(usage: Any) -> dict[str, int] | None:
    """Normalize OpenAI usage metadata for experiment and cost accounting."""

    if usage is None:
        return None
    prompt_tokens = int(_field(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(_field(usage, "completion_tokens", 0) or 0)
    total_tokens = int(
        _field(usage, "total_tokens", prompt_tokens + completion_tokens)
        or prompt_tokens + completion_tokens
    )
    prompt_details = _field(usage, "prompt_tokens_details", None)
    cached_tokens = int(_field(prompt_details, "cached_tokens", 0) or 0)
    return {
        "input_tokens": prompt_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _field(value: Any, name: str, default: Any) -> Any:
    """Read one field from an SDK model or mapping without version coupling."""

    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _system_prompt() -> str:
    """Return the strict JSON-only event-analysis prompt."""

    return (
        "You are the GeoRisk Event Analyst. Return one JSON object only. "
        "Do not include markdown, comments, tickers, price forecasts, or "
        "investment advice. Classify the news into an EventAnalysis candidate.\n\n"
        f"Allowed event_type values: {sorted(_allowed_event_types())}\n"
        f"Allowed supply_chain_nodes: {sorted(_allowed_supply_chain_nodes())}\n\n"
        "Required JSON fields: title, summary, event_type, regions, industries, "
        "supply_chain_nodes, shock_direction, risk_factors, supporting_phrases.\n"
        "supporting_phrases must be an object with keys event_type and "
        "supply_chain_nodes. Values must be short phrases copied from the "
        "original news text. If the item is out of domain or non-geopolitical, "
        "use event_type geopolitical_risk_event and supply_chain_nodes [broad_etf]."
    )


def _parse_json_object(raw_response: str) -> dict[str, Any]:
    """Parse a JSON object, allowing accidental fenced JSON wrappers."""

    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("LLM output must be a JSON object.")
    return payload


def _normalize_supporting_phrases(payload: dict[str, Any]) -> None:
    """Normalize LLM supporting phrase fields before Pydantic validation."""

    supporting_phrases = payload.get("supporting_phrases")
    if not isinstance(supporting_phrases, dict):
        supporting_phrases = {}

    supporting_phrases = {
        str(key): _to_string_list(value)
        for key, value in supporting_phrases.items()
    }
    supporting_phrases.setdefault("event_type", [])
    supporting_phrases.setdefault("supply_chain_nodes", [])
    payload["supporting_phrases"] = supporting_phrases


def _to_string_list(value: Any) -> list[str]:
    """Convert scalar, null, or mixed values into a clean list of strings."""

    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item is not None and str(item)]
    return [str(value)] if str(value) else []


def _validate_vocabularies(event: EventAnalysis) -> None:
    """Reject event types or nodes outside controlled vocabularies."""

    allowed_event_types = _allowed_event_types()
    allowed_nodes = _allowed_supply_chain_nodes()
    if event.event_type not in allowed_event_types:
        raise ValueError(f"Unsupported event_type: {event.event_type}")

    invalid_nodes = [
        node for node in event.supply_chain_nodes
        if node not in allowed_nodes
    ]
    if invalid_nodes:
        raise ValueError(f"Unsupported supply_chain_nodes: {invalid_nodes}")


def _validate_no_tickers(event: EventAnalysis, news_text: str) -> None:
    """Reject generated text that introduces known asset tickers."""

    news_upper = news_text.upper()
    generated_text = " ".join(
        [
            event.title,
            event.summary,
            event.event_type,
            event.shock_direction,
            *event.regions,
            *event.industries,
            *event.supply_chain_nodes,
            *event.risk_factors,
        ]
    ).upper()

    for ticker in _known_tickers():
        if not ticker:
            continue
        ticker_pattern = rf"(?<![A-Z0-9.]){re.escape(ticker)}(?![A-Z0-9.])"
        if (
            re.search(ticker_pattern, generated_text)
            and not re.search(ticker_pattern, news_upper)
        ):
            raise ValueError(f"LLM output introduced ticker: {ticker}")


def _validate_no_advice_or_price_language(payload: dict[str, Any]) -> None:
    """Reject investment-advice or price-prediction language."""

    text = json.dumps(payload, ensure_ascii=False).lower()
    for phrase in ADVICE_OR_PRICE_LANGUAGE:
        if " " in phrase:
            matched = phrase in text
        else:
            matched = re.search(rf"\b{re.escape(phrase)}\b", text) is not None
        if matched:
            raise ValueError("LLM output included advice or price-prediction language.")

    if re.search(r"\$[A-Z]{1,6}\b", json.dumps(payload)):
        raise ValueError("LLM output introduced ticker-like language.")


def _validate_grounding(news_text: str, supporting_phrases: dict[str, list[str]]) -> None:
    """Require most supporting phrases to appear in the original text."""

    for key in ("event_type", "supply_chain_nodes"):
        values = supporting_phrases.get(key)
        if not values:
            raise ValueError(f"LLM output must include supporting_phrases.{key}.")

    phrases = [
        phrase.strip()
        for values in supporting_phrases.values()
        for phrase in values
        if isinstance(phrase, str) and phrase.strip()
    ]
    if not phrases:
        raise ValueError("LLM output must include supporting_phrases.")

    source = news_text.lower()
    missing = [
        phrase for phrase in phrases
        if phrase.lower() not in source
    ]
    missing_ratio = len(missing) / len(phrases)
    if missing_ratio > 0.25:
        raise ValueError("Too many supporting phrases are not grounded in news_text.")


def _allowed_event_types() -> set[str]:
    """Return controlled event types allowed for LLM event analysis."""

    return {
        DEFAULT_EVENT_TYPE,
        *[str(rule["event_type"]) for rule in EVENT_RULES],
        *EXTRA_LLM_EVENT_TYPES,
    }


def _allowed_supply_chain_nodes() -> set[str]:
    """Return the controlled supply-chain node vocabulary.

    Sourced from the node registry (single source of truth), not from
    asset_mapping.csv. The mapping file is a downstream node->asset table; the
    registry is the authoritative vocabulary that both analyzers validate
    against.
    """

    return nodes.all_node_ids()


def _known_tickers() -> set[str]:
    """Return known candidate tickers from asset_mapping.csv."""

    with ASSET_MAPPING_PATH.open(encoding="utf-8") as file:
        rows = csv.DictReader(file)
        return {row["ticker"].upper() for row in rows if row.get("ticker")}
