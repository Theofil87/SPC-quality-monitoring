"""Statistical helpers for the SPC monitoring dashboard."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


MR_UCL_FACTOR = 3.267


@dataclass(frozen=True)
class MRViolationSummary:
    """Calculated moving-range limits and observations beyond the MR UCL."""

    values: pd.Series
    violations: pd.Series
    center_line: float | None
    upper_control_limit: float | None
    lower_control_limit: float | None
    valid_count: int
    violation_count: int
    violation_rate_pct: float | None
    maximum: float | None


def summarize_mr_violations(moving_ranges: pd.Series) -> MRViolationSummary:
    """Calculate MR-chart limits and flag valid moving ranges above the UCL."""
    values = pd.to_numeric(moving_ranges, errors="coerce")
    valid = values.notna() & np.isfinite(values)
    valid_values = values.loc[valid].astype(float)
    violations = pd.Series(False, index=values.index, dtype=bool)

    if valid_values.empty:
        return MRViolationSummary(
            values=values,
            violations=violations,
            center_line=None,
            upper_control_limit=None,
            lower_control_limit=None,
            valid_count=0,
            violation_count=0,
            violation_rate_pct=None,
            maximum=None,
        )

    center_line = float(valid_values.mean())
    upper_control_limit = MR_UCL_FACTOR * center_line
    violation_mask = valid & values.gt(upper_control_limit)
    violations.loc[violation_mask] = True
    violation_count = int(violations.sum())
    valid_count = len(valid_values)

    return MRViolationSummary(
        values=values,
        violations=violations,
        center_line=center_line,
        upper_control_limit=upper_control_limit,
        lower_control_limit=0.0,
        valid_count=valid_count,
        violation_count=violation_count,
        violation_rate_pct=violation_count / valid_count * 100,
        maximum=float(valid_values.max()),
    )
