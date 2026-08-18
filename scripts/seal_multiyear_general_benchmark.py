"""Seal the 2020-2025 multi-year general benchmark."""

from __future__ import annotations

import json

from src.validation.multiyear_general_benchmark import seal_multiyear_general_benchmark


if __name__ == "__main__":
    print(json.dumps(seal_multiyear_general_benchmark(), indent=2, sort_keys=True))
