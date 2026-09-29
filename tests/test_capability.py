from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.capability import calculate_capability, describe_capability_groups


def _measurements(
    values: list[float],
    *,
    shift_instances: list[str] | None = None,
    ids: list[int] | None = None,
    timestamps: list[str] | None = None,
) -> pd.DataFrame:
    count = len(values)
    return pd.DataFrame(
        {
            "measurement_id": ids or list(range(1, count + 1)),
            "measurement_timestamp": timestamps or list(
                pd.date_range("2026-01-01", periods=count, freq="min").astype(str)
            ),
            "shift_instance": shift_instances or ["shift-a"] * count,
            "measured_value": values,
            "lsl": [0.0] * count,
            "target": [5.0] * count,
            "usl": [10.0] * count,
            "spc_signal": [False] * count,
            "below_lsl": [value < 0 for value in values],
            "above_usl": [value > 10 for value in values],
            "is_oos": [value < 0 or value > 10 for value in values],
        }
    )


def test_manual_fixture_matches_hand_calculations():
    result = calculate_capability(_measurements([3, 5, 7, 9]))

    assert result["mrbar"] == pytest.approx(2)
    assert result["within_sigma"] == pytest.approx(1.773, abs=0.0001)
    assert result["overall_sigma"] == pytest.approx(2.582, abs=0.001)
    assert result["Cp"] == pytest.approx(0.94, abs=0.005)
    assert result["Cpk"] == pytest.approx(0.75, abs=0.005)
    assert result["Pp"] == pytest.approx(0.65, abs=0.005)
    assert result["Ppk"] == pytest.approx(0.52, abs=0.005)


def test_centering_changes_cpk_and_ppk_not_spread_only_indices():
    centered = calculate_capability(_measurements([2, 4, 6, 8]))
    shifted = calculate_capability(_measurements([3, 5, 7, 9]))

    assert shifted["Cp"] == pytest.approx(centered["Cp"])
    assert shifted["Pp"] == pytest.approx(centered["Pp"])
    assert shifted["Cpk"] < centered["Cpk"]
    assert shifted["Ppk"] < centered["Ppk"]


def test_specification_limits_are_inclusive_for_compliance():
    result = calculate_capability(_measurements([-0.1, 0, 5, 10, 10.1]))

    assert result["below_LSL_count"] == 1
    assert result["above_USL_count"] == 1
    assert result["OOS_count"] == 2
    assert result["OOS_rate"] == pytest.approx(2 / 5)


def test_single_observation_has_no_sigma_estimates_or_indices():
    result = calculate_capability(_measurements([5]))

    assert result["within_sigma_status"] == "NO_VALID_MR_PAIR"
    assert result["overall_sigma_status"] == "INSUFFICIENT_OBSERVATIONS"
    assert result["availability_status"] == "UNAVAILABLE"
    assert all(result[index] is None for index in ("Cp", "Cpk", "Pp", "Ppk"))


def test_no_moving_range_pair_does_not_block_overall_indices():
    result = calculate_capability(
        _measurements([4, 6], shift_instances=["shift-a", "shift-b"])
    )

    assert result["valid_mr_pairs"] == 0
    assert result["within_sigma_status"] == "NO_VALID_MR_PAIR"
    assert result["overall_sigma_status"] == "AVAILABLE"
    assert result["Cp"] is None
    assert result["Pp"] is not None
    assert result["availability_status"] == "PARTIALLY_AVAILABLE"


def test_zero_sigma_never_returns_infinite_indices():
    result = calculate_capability(_measurements([5, 5, 5]))

    assert result["within_sigma_status"] == "ZERO_SIGMA"
    assert result["overall_sigma_status"] == "ZERO_SIGMA"
    assert all(result[index] is None for index in ("Cp", "Cpk", "Pp", "Ppk"))


def test_near_zero_sigma_uses_documented_measurement_resolution_tolerance():
    result = calculate_capability(_measurements([5, 5.0001, 5.0002]))

    assert result["within_sigma_status"] == "NEAR_ZERO_SIGMA"
    assert result["overall_sigma_status"] == "NEAR_ZERO_SIGMA"
    assert all(result[index] is None for index in ("Cp", "Cpk", "Pp", "Ppk"))


def test_moving_ranges_do_not_cross_shift_instances():
    result = calculate_capability(
        _measurements([1, 2, 100, 101], shift_instances=["shift-a", "shift-a", "shift-b", "shift-b"])
    )

    assert result["valid_mr_pairs"] == 2
    assert result["mrbar"] == pytest.approx(1)


def test_timestamp_and_measurement_id_define_deterministic_tie_order():
    measurements = _measurements(
        [20, 0, 10],
        ids=[3, 1, 2],
        timestamps=["2026-01-01 00:00:00"] * 3,
    )
    result = calculate_capability(measurements)

    assert result["mrbar"] == pytest.approx(10)
    assert result["valid_mr_pairs"] == 2


def test_missing_specification_limits_are_explicitly_unavailable():
    measurements = _measurements([4, 6]).drop(columns=["lsl", "target", "usl"])
    result = calculate_capability(measurements)

    assert result["specification_status"] == "MISSING_SPECIFICATION_LIMITS"
    assert result["OOS_count"] is None
    assert all(result[index] is None for index in ("Cp", "Cpk", "Pp", "Ppk"))


def test_duplicate_measurement_ids_are_rejected():
    measurements = _measurements([4, 6])
    measurements.loc[1, "measurement_id"] = measurements.loc[0, "measurement_id"]

    with pytest.raises(ValueError, match="measurement_id must be unique"):
        calculate_capability(measurements)


def test_signal_measurements_are_retained_and_mark_result_exploratory():
    measurements = _measurements([4, 6, 7])
    measurements.loc[1, "spc_signal"] = True
    result = calculate_capability(measurements)

    assert result["measurement_count"] == 3
    assert result["spc_signal_count"] == 1
    assert result["stability_signal_status"] == "SPC_SIGNALS_PRESENT"
    assert result["interpretation_status"] == "EXPLORATORY_PHASE_I_SPC_SIGNALS_PRESENT"


def test_group_summaries_remain_descriptive_for_small_groups():
    measurements = _measurements([4, 6])
    measurements["production_month"] = ["2026-01", "2026-02"]
    summaries = describe_capability_groups(measurements, ["production_month"])

    assert summaries["measurement_count"].tolist() == [1, 1]
    assert summaries["sample_std"].isna().all()
    assert not {"Cp", "Cpk", "Pp", "Ppk"}.intersection(summaries.columns)