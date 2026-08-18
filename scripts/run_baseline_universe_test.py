"""Run the baseline-universe contamination diagnostic."""

from __future__ import annotations

import argparse
import json

from src.validation.baseline_universe_test import run_baseline_universe_contamination_test


def main() -> None:
    parser = argparse.ArgumentParser(description="Run baseline-universe contamination diagnostic.")
    parser.add_argument("--output-dir", default="data/market_validation/baseline_universe_test")
    args = parser.parse_args()

    summary = run_baseline_universe_contamination_test(output_dir=args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
