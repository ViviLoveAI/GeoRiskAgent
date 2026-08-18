"""Run the curated-pool activation / event-specific discrimination test."""

from src.validation.curated_activation_test import run_curated_activation_test


def main() -> None:
    """CLI entry point."""

    summary = run_curated_activation_test()
    construction = summary["activation_construction"]
    primary = summary["continuous_primary"]
    conclusion = summary["main_conclusion"]
    print(
        "curated activation test complete: "
        f"events={construction['events']} "
        f"eligible_rows={construction['curated_eligible_asset_event_rows']} "
        f"activated={construction['activated_rows']} "
        f"nonactivated={construction['nonactivated_rows']} "
        f"paired_events={primary['paired_eligible_events']} "
        f"conclusion={conclusion['answer']}"
    )


if __name__ == "__main__":
    main()
