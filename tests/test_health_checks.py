from __future__ import annotations

import json

import pandas as pd

from src import health_checks
from src.agents.market_mapper import REQUIRED_MAPPING_COLUMNS


def test_historical_case_health_rejects_schema_drift(tmp_path, monkeypatch):
    path = tmp_path / "historical_cases.json"
    path.write_text(json.dumps([{"event_id": "case-a"}]), encoding="utf-8")
    monkeypatch.setattr(health_checks, "HISTORICAL_CASES_PATH", path)

    result = health_checks.validate_historical_cases()

    assert result.healthy is False
    assert result.required is True
    assert result.status == "unavailable"


def test_asset_mapping_health_rejects_empty_mapping(tmp_path, monkeypatch):
    path = tmp_path / "asset_mapping.csv"
    pd.DataFrame(columns=sorted(REQUIRED_MAPPING_COLUMNS)).to_csv(
        path,
        index=False,
    )
    monkeypatch.setattr(health_checks, "ASSET_MAPPING_PATH", path)

    result = health_checks.validate_asset_mapping()

    assert result.healthy is False
    assert result.required is True


def test_missing_llm_key_is_optional_and_deterministic_mode_remains_healthy(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = health_checks.llm_configuration_health()

    assert result.status == "disabled"
    assert result.healthy is True
    assert result.required is False
