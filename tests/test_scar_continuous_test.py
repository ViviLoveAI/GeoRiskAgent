import pytest

from src.validation import scar_continuous_test as scar_test


def test_empirical_one_sided_p_value_uses_plus_one_definition():
    values = [0.1, 0.2, 0.3, 0.4]

    assert scar_test.empirical_one_sided_p_value(values, 0.3) == pytest.approx(3 / 5)


def test_event_level_comparison_uses_event_median_abs_scar():
    georisk = [
        {
            "event_id": "e1",
            "georisk_event_median_abs_scar": 1.0,
            "georisk_evaluable_assets": 2,
            "georisk_hits": 0,
            "georisk_hit_rate": 0.0,
        }
    ]
    random_by_run = {
        0: {"e1": {"median_abs_SCAR": "0.5"}},
        1: {"e1": {"median_abs_SCAR": "0.7"}},
    }

    rows = scar_test.event_level_comparison_rows(georisk, random_by_run)

    assert rows[0]["curated_random_mean_event_median_abs_scar"] == pytest.approx(0.6)
    assert rows[0]["delta_vs_random_mean_event_median_abs_scar"] == pytest.approx(0.4)
    assert rows[0]["georisk_event_percentile"] == 1.0


def test_binary_reference_keeps_threshold_as_secondary(tmp_path):
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    (baseline_dir / "random_matched_summary.json").write_text(
        """
        {
          "scopes": {
            "all": {
              "hit_rate": {"mean": 0.10, "median": 0.11, "p05": 0.05, "p95": 0.15},
              "actual_georisk_percentile_rank_hit_rate": 0.87
            }
          }
        }
        """,
        encoding="utf-8",
    )
    rows = [
        {"hit": True, "standardized_car": 2.2},
        {"hit": False, "standardized_car": -0.5},
    ]

    result = scar_test.binary_reference_summary(baseline_dir, rows)

    assert result["hit_rule"] == "abs(standardized_car) >= 1.96"
    assert result["georisk_hit_rate"] == 0.5
    assert result["delta_georisk_minus_curated_mean"] == pytest.approx(0.4)


def test_pattern_no_when_continuous_does_not_separate():
    binary = {"delta_georisk_minus_curated_mean": 0.02}
    random_values = [0.5, 0.6, 0.7, 0.8]
    event_rows = [
        {"delta_vs_random_mean_event_median_abs_scar": -0.1},
        {"delta_vs_random_mean_event_median_abs_scar": 0.1},
    ]

    result = scar_test.classify_pattern(binary, 0.55, random_values, event_rows)

    assert result["conclusion"] == "NO"
