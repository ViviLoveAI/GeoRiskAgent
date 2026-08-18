"""Seal V4 temporal held-out events and retrieval-blind annotations."""

from __future__ import annotations

import json

from src.validation.v4_temporal_heldout import seal_temporal_heldout_benchmark


def main() -> None:
    """Seal the V4 temporal held-out benchmark."""

    result = seal_temporal_heldout_benchmark()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
