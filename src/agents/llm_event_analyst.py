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
from typing import Any

from pydantic import BaseModel, Field

from src.agents.event_analyst import DEFAULT_EVENT_TYPE, EVENT_RULES, analyze_event
from src.config import ASSET_MAPPING_PATH, LLM_EVENT_ANALYST_MODEL, USE_LLM_EVENT_ANALYST
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

_last_analysis_trace: dict[str, object] = {}


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

    global _last_analysis_trace

    if not news_text.strip():
        raise ValueError("news_text must not be empty.")

    _log_runtime_status()
    _last_analysis_trace = {
        "openai_api_key_detected": bool(os.getenv("OPENAI_API_KEY")),
        "use_llm_event_analyst": USE_LLM_EVENT_ANALYST,
        "model": LLM_EVENT_ANALYST_MODEL,
        "api_call_attempted": False,
        "fallback_occurred": False,
        "fallback_reason": None,
        "supporting_phrases": {},
    }
    api_call_attempted = False
    try:
        api_call_attempted = True
        _last_analysis_trace["api_call_attempted"] = True
        _log("OpenAI API call attempted: yes")
        raw_response = _call_llm(news_text)
        payload = _parse_json_object(raw_response)
        _normalize_supporting_phrases(payload)
        candidate = LLMEventAnalysisCandidate.model_validate(payload)
        event = EventAnalysis.model_validate(candidate.model_dump(exclude={"supporting_phrases"}))
        _validate_vocabularies(event)
        _validate_no_tickers(event, news_text)
        _validate_no_advice_or_price_language(payload)
        _validate_grounding(news_text, candidate.supporting_phrases)
        _last_analysis_trace["supporting_phrases"] = candidate.supporting_phrases
        _log("Fallback to rule-based analyzer: no")
        return event
    except Exception as exc:
        if not api_call_attempted:
            _log("OpenAI API call attempted: no")
        _log("Fallback to rule-based analyzer: yes")
        _log(f"Fallback reason: {type(exc).__name__}: {exc}")
        fallback_event = analyze_event(news_text)
        _last_analysis_trace["fallback_occurred"] = True
        _last_analysis_trace["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        _last_analysis_trace["supporting_phrases"] = {
            "rule_based_keywords": fallback_event.risk_factors,
        }
        return fallback_event


def get_last_analysis_trace() -> dict[str, object]:
    """Return observability metadata for the most recent LLM analysis."""

    return dict(_last_analysis_trace)


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

    client = OpenAI()
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
    content = response.choices[0].message.content
    if not content:
        raise ValueError("LLM returned empty content.")
    return content


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
    """Return controlled supply-chain nodes from asset_mapping.csv."""

    with ASSET_MAPPING_PATH.open(encoding="utf-8") as file:
        rows = csv.DictReader(file)
        return {row["supply_chain_node"] for row in rows if row.get("supply_chain_node")}


def _known_tickers() -> set[str]:
    """Return known candidate tickers from asset_mapping.csv."""

    with ASSET_MAPPING_PATH.open(encoding="utf-8") as file:
        rows = csv.DictReader(file)
        return {row["ticker"].upper() for row in rows if row.get("ticker")}
