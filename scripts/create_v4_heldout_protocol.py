"""Create the GeoRisk V4 untouched held-out validation protocol scaffold."""

from __future__ import annotations

import argparse
import json

from src.validation.v4_heldout_protocol import (
    DEFAULT_FREEZE_CHECKSUMS_PATH,
    DEFAULT_FREEZE_MANIFEST_PATH,
    DEFAULT_PROTOCOL_DIR,
    create_v4_heldout_protocol,
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for protocol scaffold creation."""

    parser = argparse.ArgumentParser(
        description="Create V4 held-out protocol artifacts without selecting events or running CAR.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_PROTOCOL_DIR))
    parser.add_argument("--freeze-manifest", default=str(DEFAULT_FREEZE_MANIFEST_PATH))
    parser.add_argument("--freeze-checksums", default=str(DEFAULT_FREEZE_CHECKSUMS_PATH))
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing protocol scaffold artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    """Create the V4 held-out protocol scaffold."""

    args = parse_args()
    result = create_v4_heldout_protocol(
        output_dir=args.output_dir,
        freeze_manifest_path=args.freeze_manifest,
        freeze_checksums_path=args.freeze_checksums,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
