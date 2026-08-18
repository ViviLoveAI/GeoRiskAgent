"""Run the binary-SCAR threshold compression diagnostic."""

from __future__ import annotations

import argparse
import json

from src.validation.scar_continuous_test import run_continuous_scar_compression_test


def main() -> None:
    parser = argparse.ArgumentParser(description="Run continuous |SCAR| compression test.")
    parser.add_argument("--output-dir", default="data/market_validation/scar_continuous_test")
    args = parser.parse_args()

    summary = run_continuous_scar_compression_test(output_dir=args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
