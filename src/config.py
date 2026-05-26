"""Configuration helpers for GeoRisk Transmission Analyzer.

The project is constrained to use local, auditable inputs:
- candidate assets from ``data/asset_mapping.csv``
- historical cases from ``data/historical_cases.json``

No module in this project should predict stock prices or provide investment
advice.
"""

import os
from pathlib import Path
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
ASSET_MAPPING_PATH = DATA_DIR / "asset_mapping.csv"
HISTORICAL_CASES_PATH = DATA_DIR / "historical_cases.json"
USE_LLM_EVENT_ANALYST = os.getenv("USE_LLM_EVENT_ANALYST", "true").lower() == "true"
LLM_EVENT_ANALYST_MODEL = os.getenv("LLM_EVENT_ANALYST_MODEL", "gpt-4.1-mini")


class Settings(BaseModel):
    """Runtime settings for the analyzer."""

    asset_mapping_path: Path = Field(default=ASSET_MAPPING_PATH)
    historical_cases_path: Path = Field(default=HISTORICAL_CASES_PATH)


def get_settings() -> Settings:
    """Return default project settings.

    Future logic can add environment-specific overrides here while preserving
    the local data-source constraints.
    """

    return Settings()
