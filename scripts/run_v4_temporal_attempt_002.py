"""Run Temporal Prediction Attempt 002 as a controlled execution retry."""

from __future__ import annotations

import json
from pathlib import Path

from src.validation.v4_temporal_prediction import (
    ATTEMPT_001_ID,
    ATTEMPT_002_ID,
    evaluate_frozen_temporal_mechanisms,
    run_and_freeze_temporal_predictions,
)


ATTEMPT_002_PREDICTION_DIR = Path("data/validation_v4/predictions/attempt_002")
ATTEMPT_002_RESULTS_DIR = Path("data/validation_v4/results/attempt_002")


def main() -> None:
    """Run frozen V4 prediction retry, seal snapshots, then evaluate mechanisms."""

    prediction_result = run_and_freeze_temporal_predictions(
        prediction_dir=ATTEMPT_002_PREDICTION_DIR,
        attempt_id=ATTEMPT_002_ID,
        parent_attempt=ATTEMPT_001_ID,
        retry_reason="execution_client_lifecycle_fix",
        attempt_type="controlled_execution_retry",
        allow_controlled_retry_after_frozen=True,
    )
    mechanism_summary = evaluate_frozen_temporal_mechanisms(
        node_snapshot_path=ATTEMPT_002_PREDICTION_DIR / "v4_temporal_prediction_snapshot.csv",
        prediction_checksums_path=ATTEMPT_002_PREDICTION_DIR
        / "v4_temporal_prediction_checksums.json",
        output_path=ATTEMPT_002_RESULTS_DIR / "v4_temporal_mechanism_evaluation.csv",
        summary_path=ATTEMPT_002_RESULTS_DIR
        / "v4_temporal_mechanism_evaluation_summary.json",
        error_path=ATTEMPT_002_RESULTS_DIR / "v4_temporal_error_analysis.csv",
    )
    print(
        json.dumps(
            {"prediction": prediction_result, "mechanism_evaluation": mechanism_summary},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
