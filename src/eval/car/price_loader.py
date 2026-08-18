"""CSV loading helpers for CAR validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_csv(path: str | Path, required_columns: list[str]) -> pd.DataFrame:
    """Load a CSV and validate that required columns are present."""

    frame = pd.read_csv(path)
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")
    return frame


def load_price_csv(path: str | Path, required_columns: list[str]) -> pd.DataFrame:
    """Load long-format adjusted-close prices with normalized dates."""

    frame = load_csv(path, required_columns).copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].astype(str)
    frame["adj_close"] = pd.to_numeric(frame["adj_close"], errors="coerce")
    return frame.dropna(subset=["date", "symbol", "adj_close"])
