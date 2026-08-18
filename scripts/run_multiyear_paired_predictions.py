"""Run frozen V3/V4 multi-year paired predictions and evaluation."""

from __future__ import annotations

import argparse
import json

from src.validation.multiyear_paired_prediction import (
    run_and_evaluate_multiyear_paired_predictions,
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Run frozen V3/V4 paired multi-year predictions.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing prediction artifacts. Use only before snapshots are frozen.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(
        json.dumps(
            run_and_evaluate_multiyear_paired_predictions(overwrite=args.overwrite),
            indent=2,
            sort_keys=True,
        )
    )
