"""Input-language normalization for GeoRisk production requests.

This layer prepares user-supplied event text for the current English V4
pipeline. It translates/normalizes only the user's provided facts; it does not
add geopolitical interpretation, market analysis, or investment advice.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from src.config import LLM_EVENT_ANALYST_MODEL


logger = logging.getLogger(__name__)


class InputNormalizationError(RuntimeError):
    """Raised when non-English input cannot be normalized."""


@dataclass(frozen=True)
class NormalizedInput:
    """Input text prepared for the existing English V4 pipeline."""

    original_text: str
    analysis_text: str
    detected_language: str
    normalization_applied: bool = False
    normalization_error: str | None = None


def normalize_event_input(text: str) -> NormalizedInput:
    """Detect language and return English analysis text when possible."""

    stripped = text.strip()
    if not stripped:
        raise ValueError("event input must not be empty.")

    language = detect_language(stripped)
    if language == "English":
        return NormalizedInput(
            original_text=stripped,
            analysis_text=stripped,
            detected_language=language,
            normalization_applied=False,
        )

    try:
        normalized = _normalize_non_english_with_model(stripped)
    except Exception as exc:
        logger.exception("GeoRisk input normalization failed for detected_language=%s", language)
        return NormalizedInput(
            original_text=stripped,
            analysis_text=stripped,
            detected_language=language,
            normalization_applied=False,
            normalization_error=f"{type(exc).__name__}: {exc}",
        )

    return NormalizedInput(
        original_text=stripped,
        analysis_text=normalized,
        detected_language=language,
        normalization_applied=True,
    )


def detect_language(text: str) -> str:
    """Return a lightweight language label without user configuration."""

    if re.search(r"[\u3400-\u9fff]", text):
        return "Chinese"
    if re.search(r"[\u3040-\u30ff]", text):
        return "Japanese"
    if re.search(r"[\uac00-\ud7af]", text):
        return "Korean"
    if re.search(r"[\u0400-\u04ff]", text):
        return "Cyrillic"
    if re.search(r"[\u0600-\u06ff]", text):
        return "Arabic"

    ascii_letters = sum(1 for char in text if char.isascii() and char.isalpha())
    latin_letters = sum(1 for char in text if char.isalpha())
    if latin_letters and ascii_letters / latin_letters < 0.75:
        return "Non-English"
    return "English"


def _normalize_non_english_with_model(text: str) -> str:
    """Translate non-English event input to concise English using OpenAI."""

    if not os.getenv("OPENAI_API_KEY"):
        raise InputNormalizationError("OPENAI_API_KEY is not configured.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise InputNormalizationError("openai package is not installed.") from exc

    client = OpenAI()
    response = client.chat.completions.create(
        model=LLM_EVENT_ANALYST_MODEL,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Translate the supplied geopolitical event into concise English while "
                    "preserving all factual content, named entities, locations, industries, "
                    "commodities, and uncertainty. Do not add interpretation, new facts, "
                    "market analysis, tickers, investment advice, or price predictions. "
                    "Return plain English text only."
                ),
            },
            {"role": "user", "content": text},
        ],
    )
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise InputNormalizationError("normalization model returned empty text.")
    return content.strip()
