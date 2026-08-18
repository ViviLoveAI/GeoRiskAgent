"""Run and freeze V4 temporal held-out predictions, then evaluate mechanisms."""

from __future__ import annotations

import argparse
import json

from src.validation.v4_temporal_prediction import (
    evaluate_frozen_temporal_mechanisms,
    run_and_freeze_temporal_predictions,
)


def parse_args() -> argparse.Namespace:
    """Parse temporal prediction CLI options."""

    parser = argparse.ArgumentParser(
        description="Run frozen V4 temporal held-out prediction and freeze snapshots.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite prediction snapshots. Use only before a snapshot is considered frozen.",
    )
    parser.add_argument(
        "--skip-evaluation",
        action="store_true",
        help="Only generate prediction snapshots; do not read frozen ground truth.",
    )
    return parser.parse_args()


def main() -> None:
    """Run frozen prediction and optional mechanism evaluation."""

    args = parse_args()
    prediction_result = run_and_freeze_temporal_predictions(overwrite=args.overwrite)
    result = {"prediction": prediction_result}
    if not args.skip_evaluation:
        result["mechanism_evaluation"] = evaluate_frozen_temporal_mechanisms()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
