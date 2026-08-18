"""Build the post-freeze compatible-node funnel for Attempt 002."""

from __future__ import annotations

import json

from src.validation.v4_compatible_node_funnel import build_compatible_node_funnel


def main() -> None:
    """Run the derived funnel analysis."""

    print(json.dumps(build_compatible_node_funnel(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
