"""Run the broad-market random baseline experiment."""

from __future__ import annotations

import argparse
import json

from src.validation.broad_random_baseline import run_broad_market_random_baseline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Broad Market Random Baseline.")
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--random-seed", type=int, default=20260805)
    args = parser.parse_args()
    summary = run_broad_market_random_baseline(draws=args.draws, random_seed=args.random_seed)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
