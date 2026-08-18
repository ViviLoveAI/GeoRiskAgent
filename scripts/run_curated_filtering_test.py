"""Run the curated-pool selected-vs-rejected filtering diagnostic."""

from src.validation.curated_filtering_test import run_curated_filtering_test


def main() -> None:
    """CLI entry point."""

    summary = run_curated_filtering_test()
    reconstruction = summary["candidate_reconstruction"]
    evaluability = summary["evaluability"]
    conclusion = summary["main_conclusion"]
    print(
        "curated filtering diagnostic complete: "
        f"events={reconstruction['events']} "
        f"candidates={reconstruction['total_event_specific_candidates']} "
        f"selected={reconstruction['selected_candidates']} "
        f"rejected={reconstruction['rejected_candidates']} "
        f"paired_events={evaluability['paired_eligible_events']} "
        f"conclusion={conclusion['answer']}"
    )


if __name__ == "__main__":
    main()
