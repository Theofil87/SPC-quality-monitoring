from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.spc_monitoring import fit_baseline, summarize_mr_violations

SHIFT_A = (1, pd.Timestamp("2026-03-01 06:00"))
SHIFT_B = (2, pd.Timestamp("2026-03-01 14:00"))
SHIFT_C = (1, pd.Timestamp("2026-03-02 06:00"))


def _records(values, shifts=None):
    count = len(values)
    return pd.DataFrame(
        {
            "measurement_timestamp": pd.date_range("2026-03-01", periods=count, freq="min"),
            "measurement_id": list(range(1, count + 1)),
            "booth_id": [1] * count,
            "measurement_point_id": [1] * count,
            "specification_id": [1] * count,
            "shift_instance": [SHIFT_A] * count if shifts is None else shifts,
            "measured_value": values,
        }
    )


def test_fit_baseline_matches_known_calculations():
    limits = fit_baseline(_records([1.0, 2.0, 4.0, 7.0]))

    assert limits.n_observations == 4
    assert limits.n_valid_mr == 3
    assert limits.center_line == pytest.approx(3.5)
    assert limits.mr_center == pytest.approx(2.0)
    assert limits.sigma == pytest.approx(2.0 / 1.128)
    assert limits.i_lcl == pytest.approx(3.5 - 3 * (2.0 / 1.128))
    assert limits.i_ucl == pytest.approx(3.5 + 3 * (2.0 / 1.128))
    assert limits.mr_ucl == pytest.approx(3.267 * 2.0)


def test_fit_baseline_accepts_two_observations():
    limits = fit_baseline(_records([2.0, 4.0]))

    assert limits.n_observations == 2
    assert limits.n_valid_mr == 1
    assert limits.center_line == pytest.approx(3.0)
    assert limits.mr_center == pytest.approx(2.0)


def test_baseline_migration_enforces_fit_counts_and_limit_formulas():
    migration_path = REPO_ROOT / "sql" / "migrations" / "001_create_spc_baseline.sql"
    migration = re.sub(r"\s+", " ", migration_path.read_text(encoding="utf-8"))

    assert re.search(
        r"n_observations >= 2 AND n_valid_mr >= 1 "
        r"AND n_valid_mr < n_observations",
        migration,
    )
    assert re.search(
        r"status <> 'RETIRED' OR effective_to IS NOT NULL",
        migration,
    )
    for formula in (
        r"abs\(sigma - mr_center / 1\.128\) <= 0\.000003",
        r"abs\(i_lcl - \(center_line - 3 \* sigma\)\) <= 0\.000003",
        r"abs\(i_ucl - \(center_line \+ 3 \* sigma\)\) <= 0\.000003",
        r"abs\(mr_ucl - 3\.267 \* mr_center\) <= 0\.000003",
    ):
        assert re.search(formula, migration)


def test_fit_baseline_rejects_empty_input():
    with pytest.raises(ValueError, match="must not be empty"):
        fit_baseline(_records([]))


def test_fit_baseline_rejects_single_observation():
    with pytest.raises(ValueError, match="at least two"):
        fit_baseline(_records([1.0]))


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), -float("inf")])
def test_fit_baseline_rejects_non_finite_measurements(invalid_value):
    with pytest.raises(ValueError, match="finite"):
        fit_baseline(_records([1.0, invalid_value]))


def test_fit_baseline_rejects_non_numeric_measurements():
    with pytest.raises(ValueError, match="numeric"):
        fit_baseline(_records([1.0, "not a measurement"]))


def test_fit_baseline_rejects_separate_sequences():
    with pytest.raises(TypeError, match="DataFrame"):
        fit_baseline([1.0, 2.0])
    with pytest.raises(TypeError, match="shift_instances"):
        fit_baseline(_records([1.0, 2.0]), shift_instances=["a", "a"])


def test_fit_baseline_excludes_boundary_between_two_shifts():
    limits = fit_baseline(_records(
        [1.0, 3.0, 100.0, 104.0], [SHIFT_A, SHIFT_A, SHIFT_B, SHIFT_B]
    ))
    assert limits.n_observations == 4
    assert limits.n_valid_mr == 2
    assert limits.center_line == pytest.approx(52.0)
    assert limits.mr_center == pytest.approx(3.0)
    assert limits.sigma == pytest.approx(3.0 / 1.128)
    assert limits.i_lcl == pytest.approx(52.0 - 3 * (3.0 / 1.128))
    assert limits.i_ucl == pytest.approx(52.0 + 3 * (3.0 / 1.128))
    assert limits.mr_ucl == pytest.approx(3.267 * 3.0)


def test_fit_baseline_pools_within_shift_pairs_even_when_interleaved():
    limits = fit_baseline(_records(
        [10.0, 100.0, 30.0, 13.0, 106.0, 32.0, 110.0],
        [SHIFT_A, SHIFT_B, SHIFT_C, SHIFT_A, SHIFT_B, SHIFT_C, SHIFT_B],
    ))
    assert limits.n_observations == 7
    assert limits.n_valid_mr == 4
    assert limits.mr_center == pytest.approx((3 + 6 + 2 + 4) / 4)


def test_fit_baseline_single_observation_shift_contributes_no_mr():
    limits = fit_baseline(_records([1.0, 2.0, 100.0, 10.0, 12.0],
                                   [SHIFT_A, SHIFT_A, SHIFT_B, SHIFT_C, SHIFT_C]))
    assert limits.n_observations == 5
    assert limits.n_valid_mr == 2
    assert limits.center_line == pytest.approx(25.0)
    assert limits.mr_center == pytest.approx(1.5)


def test_fit_baseline_rejects_input_without_within_shift_pairs():
    with pytest.raises(ValueError, match="within-shift moving range"):
        fit_baseline(_records([1.0, 2.0], [SHIFT_A, SHIFT_B]))


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), "missing"])
def test_fit_baseline_rejects_invalid_values_with_shift_keys(invalid):
    with pytest.raises(ValueError):
        fit_baseline(_records([1.0, invalid, 3.0], [SHIFT_A, SHIFT_A, SHIFT_B]))


@pytest.mark.parametrize("key", [
    None, float("nan"), "", " ", (), (2,), (2, None), (2, ""),
    (2, "invalid"), (2, "2026-03-01T00:00:00Z"), (2, "2026-03-01", 3),
    (0, "2026-03-01"), (True, "2026-03-01"), (2, []), 1, ["unhashable"],
])
def test_fit_baseline_rejects_invalid_shift_keys(key):
    with pytest.raises(ValueError, match="shift_instance"):
        fit_baseline(_records([1.0, 2.0], [SHIFT_A, key]))


def test_fit_baseline_sorts_complete_unsorted_records_without_mutating_input():
    records = _records(
        [0.0, 0.0, 10.0, 10.0, 100.0, 104.0],
        [SHIFT_A, SHIFT_A, SHIFT_A, SHIFT_A, SHIFT_B, SHIFT_B],
    )
    records = records.iloc[[0, 2, 4, 1, 5, 3]]
    original = records.copy(deep=True)
    limits = fit_baseline(records)
    assert limits.n_valid_mr == 4
    assert limits.mr_center == pytest.approx(3.5)
    pd.testing.assert_frame_equal(records, original)


def test_fit_baseline_breaks_timestamp_ties_by_measurement_id():
    records = _records([0.0, 10.0, 0.0])
    records["measurement_timestamp"] = pd.Timestamp("2026-03-01")
    records = records.iloc[[0, 2, 1]]
    limits = fit_baseline(records)
    assert limits.n_valid_mr == 2
    assert limits.mr_center == pytest.approx(10.0)


def test_fit_baseline_keeps_overnight_shift_together():
    night = (3, pd.Timestamp("2026-03-01 22:00"))
    day = (1, pd.Timestamp("2026-03-02 06:00"))
    records = _records([10.0, 14.0, 100.0, 103.0], [night, night, day, day])
    records["measurement_timestamp"] = pd.to_datetime(
        ["2026-03-01 23:30", "2026-03-02 00:30",
         "2026-03-02 06:00", "2026-03-02 07:00"]
    )
    limits = fit_baseline(records.iloc[[3, 1, 2, 0]])
    assert limits.n_valid_mr == 2
    assert limits.mr_center == pytest.approx(3.5)


@pytest.mark.parametrize("column", [
    "booth_id", "measurement_point_id", "specification_id",
    "measurement_timestamp", "measurement_id", "shift_instance", "measured_value",
])
def test_fit_baseline_requires_columns(column):
    with pytest.raises(ValueError, match="missing required columns"):
        fit_baseline(_records([1.0, 2.0]).drop(columns=column))


@pytest.mark.parametrize("invalid", [None, pd.NaT, "invalid", 123, "2026-01-01T00:00:00Z"])
def test_fit_baseline_rejects_invalid_timestamps(invalid):
    records = _records([1.0, 2.0])
    records["measurement_timestamp"] = records["measurement_timestamp"].astype(object)
    records.loc[1, "measurement_timestamp"] = invalid
    with pytest.raises(ValueError, match="measurement_timestamp"):
        fit_baseline(records)


@pytest.mark.parametrize("invalid", [None, 0, -1, 1.5, "2", True, 9223372036854775808])
def test_fit_baseline_rejects_invalid_measurement_ids(invalid):
    records = _records([1.0, 2.0])
    records["measurement_id"] = pd.Series([1, invalid], dtype=object)
    with pytest.raises(ValueError, match="measurement_id"):
        fit_baseline(records)


def test_fit_baseline_rejects_duplicate_measurement_ids():
    records = _records([1.0, 2.0])
    records["measurement_id"] = [1, 1]
    with pytest.raises(ValueError, match="unique"):
        fit_baseline(records)


def test_fit_baseline_rejects_duplicate_columns():
    records = _records([1.0, 2.0])
    records = pd.concat([records, records[["shift_instance"]]], axis=1)
    with pytest.raises(ValueError, match="columns must be unique"):
        fit_baseline(records)


@pytest.mark.parametrize("column", ["booth_id", "measurement_point_id", "specification_id"])
def test_fit_baseline_rejects_mixed_scope(column):
    records = _records([1.0, 2.0])
    records.loc[1, column] = 2
    with pytest.raises(ValueError, match="one scope"):
        fit_baseline(records)


@pytest.mark.parametrize("invalid", [None, 0, -1, 1.5, "1", True, 2147483648])
def test_fit_baseline_rejects_invalid_scope_ids(invalid):
    records = _records([1.0, 2.0])
    records["booth_id"] = pd.Series([1, invalid], dtype=object)
    with pytest.raises(ValueError, match="booth_id"):
        fit_baseline(records)


def test_fit_baseline_distinguishes_same_shift_type_on_different_days():
    limits = fit_baseline(_records(
        [1.0, 3.0, 100.0, 104.0],
        [SHIFT_A, SHIFT_A, SHIFT_C, SHIFT_C],
    ))
    assert limits.n_valid_mr == 2
    assert limits.mr_center == pytest.approx(3.0)


def test_fit_baseline_preserves_numeric_source_precision_at_bounds():
    limits = fit_baseline(_records([
        Decimal("9999999.998"), Decimal("9999999.999"),
    ]))
    assert limits.n_valid_mr == 1
    assert limits.mr_center == pytest.approx(0.001, abs=1e-8)
    assert limits.center_line == pytest.approx(9999999.9985, rel=0, abs=1e-8)
    negative = fit_baseline(_records([
        Decimal("-9999999.999"), Decimal("-9999999.998"),
    ]))
    assert negative.mr_center == pytest.approx(0.001, abs=1e-8)


@pytest.mark.parametrize("invalid", [
    Decimal("10000000.000"), Decimal("-10000000.000"),
    Decimal("0.0001"), Decimal("1.2345"), 9007199254740993,
])
def test_fit_baseline_rejects_values_outside_numeric_source_domain(invalid):
    with pytest.raises(ValueError, match=r"NUMERIC\(10,3\)"):
        fit_baseline(_records([Decimal("1.000"), invalid]))


@pytest.mark.parametrize("values", [
    [Decimal("-9999999.999"), Decimal("9999999.999")],
    [Decimal("9999999.998"), Decimal("9999999.999")],
    [Decimal("1.000"), Decimal("1.000")],
])
def test_fit_baseline_rounded_limits_fit_storage_and_formula_tolerance(values):
    limits = fit_baseline(_records(values))
    rounded = {
        name: Decimal(str(getattr(limits, name))).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
        for name in ("center_line", "sigma", "i_lcl", "i_ucl", "mr_center", "mr_ucl")
    }
    assert all(abs(value) <= Decimal("99999999.999999") for value in rounded.values())
    tolerance = Decimal("0.000003")
    assert abs(rounded["sigma"] - rounded["mr_center"] / Decimal("1.128")) <= tolerance
    assert abs(rounded["i_lcl"] - (rounded["center_line"] - 3 * rounded["sigma"])) <= tolerance
    assert abs(rounded["i_ucl"] - (rounded["center_line"] + 3 * rounded["sigma"])) <= tolerance
    assert abs(rounded["mr_ucl"] - Decimal("3.267") * rounded["mr_center"]) <= tolerance


def test_fit_baseline_supports_zero_moving_range():
    limits = fit_baseline(_records([5.0, 5.0, 5.0]))

    assert limits.mr_center == 0.0
    assert limits.sigma == 0.0
    assert limits.i_lcl == 5.0
    assert limits.i_ucl == 5.0
    assert limits.mr_ucl == 0.0


def test_mr_ucl_uses_mean_of_valid_moving_ranges():
    summary = summarize_mr_violations(pd.Series([None, 1.0, 2.0, 3.0]))

    assert summary.center_line == pytest.approx(2.0)
    assert summary.upper_control_limit == pytest.approx(3.267 * 2.0)
    assert summary.lower_control_limit == 0.0
    assert summary.valid_count == 3


def test_mr_violations_and_rate_use_valid_moving_ranges():
    summary = summarize_mr_violations(
        pd.Series([None, 1.0, 1.0, 1.0, 1.0, 10.0])
    )

    assert summary.violations.tolist() == [False, False, False, False, False, True]
    assert summary.violation_count == 1
    assert summary.violation_rate_pct == pytest.approx(20.0)
    assert summary.maximum == pytest.approx(10.0)


def test_null_moving_ranges_are_not_violations():
    summary = summarize_mr_violations(pd.Series([None, 1.0, 2.0]))

    assert not summary.violations.iloc[0]
    assert summary.violations.iloc[1:].eq(False).all()


def test_empty_moving_range_input_returns_unavailable_limits_and_metrics():
    summary = summarize_mr_violations(pd.Series(dtype="float64"))

    assert summary.valid_count == 0
    assert summary.violation_count == 0
    assert summary.center_line is None
    assert summary.upper_control_limit is None
    assert summary.lower_control_limit is None
    assert summary.violation_rate_pct is None
    assert summary.maximum is None
    assert summary.violations.empty
