from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.drift_shift_analysis import (
    calculate_rolling_shift_instance_means,
    calculate_trend_diagnostics,
    calculate_variation_decomposition,
    first_half_second_half_comparison,
    summarize_drift_shift_inputs,
)


def _measurements(
    values: list[float] = [1, 3, 5, 7],
    *,
    instances: list[str] | None = None,
    shift_ids: list[int] | None = None,
    production_months: list[str] | None = None,
    signals: list[bool] | None = None,
) -> pd.DataFrame:
    count = len(values)
    instances = instances or ["2026-01-01 06:00"] * count
    return pd.DataFrame(
        {
            "measurement_id": list(range(1, count + 1)),
            "measurement_timestamp": pd.date_range("2026-01-01 06:00", periods=count, freq="min"),
            "production_month": production_months or ["2026-01-01"] * count,
            "shift_instance": instances,
            "shift_id": shift_ids or [1] * count,
            "shift_name": [f"SHIFT_{value:02d}" for value in (shift_ids or [1] * count)],
            "measured_value": values,
            "target": [4.0] * count,
            "below_lsl": [value < 0 for value in values],
            "above_usl": [value > 6 for value in values],
            "is_oos": [value < 0 or value > 6 for value in values],
            "spc_signal": signals or [False] * count,
        }
    )


def test_monthly_aggregation_uses_correct_counts_rates_and_target_deviation():
    data = _measurements(
        [1, 3, 5, 7],
        production_months=["2026-01-01", "2026-01-01", "2026-02-01", "2026-02-01"],
        signals=[False, True, False, True],
    )
    monthly = summarize_drift_shift_inputs(data)["monthly"]
    assert monthly["measurement_count"].tolist() == [2, 2]
    assert monthly["oos_count"].tolist() == [0, 1]
    assert monthly["oos_rate"].tolist() == [0.0, 0.5]
    assert monthly["spc_signal_rate"].tolist() == [0.5, 0.5]
    assert monthly["mean_deviation_from_target"].tolist() == [-2.0, 2.0]


def test_same_shift_type_remains_separate_actual_shift_instances_then_pools():
    data = _measurements(
        [1, 3, 5, 7],
        instances=["2026-01-01 06:00"] * 2 + ["2026-01-02 06:00"] * 2,
    )
    summaries = summarize_drift_shift_inputs(data)
    assert len(summaries["shift_instance"]) == 2
    assert summaries["shift_instance"]["measurement_count"].tolist() == [2, 2]
    assert len(summaries["shift_type"]) == 1
    assert summaries["shift_type"].loc[0, "shift_instance_count"] == 2
    assert summaries["shift_type"].loc[0, "measurement_count"] == 4


def test_overnight_shift_is_a_single_actual_shift_instance():
    data = _measurements(
        [3, 5],
        instances=["2026-01-01 22:00", "2026-01-01 22:00"],
        shift_ids=[3, 3],
    )
    data.loc[1, "measurement_timestamp"] = pd.Timestamp("2026-01-02 01:00")
    summary = summarize_drift_shift_inputs(data)["shift_instance"]
    assert len(summary) == 1
    assert summary.loc[0, "shift_instance"] == pd.Timestamp("2026-01-01 22:00")
    assert summary.loc[0, "measurement_count"] == 2


def test_shift_type_pooling_preserves_supplied_spc_flags():
    data = _measurements(
        [1, 3, 5, 7],
        instances=["2026-01-01 06:00"] * 2 + ["2026-01-01 14:00"] * 2,
        shift_ids=[1, 1, 2, 2],
        signals=[True, False, True, True],
    )
    shift_type = summarize_drift_shift_inputs(data)["shift_type"]
    assert shift_type["spc_signal_count"].tolist() == [1, 2]
    assert shift_type["spc_signal_rate"].tolist() == [0.5, 1.0]


def test_rolling_windows_are_chronological_and_require_full_window():
    summary = pd.DataFrame(
        {"shift_instance": pd.date_range("2026-01-01", periods=4, freq="D")[::-1], "mean": [4, 3, 2, 1]}
    )
    result = calculate_rolling_shift_instance_means(summary, windows=(2, 3))
    assert result["mean"].tolist() == [1, 2, 3, 4]
    assert result["rolling_mean_2"].isna().sum() == 1
    assert result["rolling_mean_2"].iloc[-1] == pytest.approx(3.5)
    assert result["rolling_mean_3"].iloc[-1] == pytest.approx(3.0)


def test_trend_slope_and_first_second_half_are_deterministic():
    summary = pd.DataFrame(
        {"shift_instance": pd.date_range("2026-01-01", periods=6, freq="D"), "mean": [1, 3, 5, 7, 9, 11]}
    )
    trend = calculate_trend_diagnostics(summary)
    comparison = first_half_second_half_comparison(summary)
    assert trend["slope_per_day"] == pytest.approx(2.0)
    assert trend["estimated_cumulative_fitted_change"] == pytest.approx(10.0)
    assert comparison["second_minus_first_mean"] == pytest.approx(6.0)
    assert comparison["first_half_shift_instance_count"] == 3
    assert comparison["second_half_shift_instance_count"] == 3


def test_first_second_half_odd_count_assigns_middle_to_later_half():
    summary = pd.DataFrame(
        {"shift_instance": pd.date_range("2026-01-01", periods=5, freq="D"), "mean": [1, 2, 3, 4, 5]}
    )
    result = first_half_second_half_comparison(summary)
    assert result["first_half_shift_instance_count"] == 2
    assert result["second_half_shift_instance_count"] == 3
    assert result["second_minus_first_mean"] == pytest.approx(2.5)


def test_sum_of_squares_decomposition_reconciles_and_shift_centres_add_variation():
    data = _measurements(
        [0, 2, 10, 12],
        instances=["2026-01-01 06:00"] * 2 + ["2026-01-02 06:00"] * 2,
    )
    result = calculate_variation_decomposition(data)
    assert result["total_sum_of_squares"] == pytest.approx(
        result["within_shift_sum_of_squares"] + result["between_shift_sum_of_squares"]
    )
    assert result["within_shift_sum_of_squares"] == pytest.approx(4.0)
    assert result["between_shift_sum_of_squares"] == pytest.approx(100.0)
    assert result["overall_sample_sd"] > result["pooled_within_shift_sd"]
    assert result["subgroup_size_distribution"].to_dict("records") == [
        {"measurement_count": 2, "shift_instance_count": 2}
    ]


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda frame: frame.assign(measurement_id=[1, 1, 3, 4]), "measurement_id"),
        (lambda frame: frame.drop(columns=["target"]), "Missing required"),
        (lambda frame: frame.assign(measured_value=[1, np.nan, 5, 7]), "measured_value"),
        (lambda frame: frame.assign(shift_name=["A", "B", "SHIFT_01", "SHIFT_01"]), "shift_instance"),
    ],
)
def test_invalid_input_is_rejected(mutator, message):
    with pytest.raises(ValueError, match=message):
        summarize_drift_shift_inputs(mutator(_measurements()))
