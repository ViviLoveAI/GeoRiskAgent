"""Run the scoped V5 node-repair temporal held-out A/B evaluation."""

from __future__ import annotations

import json

from src.validation.v5_node_repair_ab import run_v5_node_repair_ab


def main() -> None:
    """Run the evaluation and print the summary artifact."""

    print(json.dumps(run_v5_node_repair_ab(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
