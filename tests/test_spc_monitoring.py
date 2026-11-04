from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.spc_monitoring import summarize_mr_violations


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
