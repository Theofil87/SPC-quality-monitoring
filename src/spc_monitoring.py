"""Statistical helpers for the SPC monitoring dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from numbers import Integral

import numpy as np
import pandas as pd


MR_UCL_FACTOR = 3.267
_MEASUREMENT_MAX = Decimal("9999999.999")
_BASELINE_MAX = Decimal("99999999.999999")
_MEASUREMENT_QUANTUM = Decimal("0.001")
_BASELINE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class BaselineLimits:
    """Fixed I-chart and MR-chart limits calculated from baseline measurements."""

    n_observations: int
    n_valid_mr: int
    center_line: float
    sigma: float
    i_lcl: float
    i_ucl: float
    mr_center: float
    mr_ucl: float


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


def fit_baseline(measurements: pd.DataFrame) -> BaselineLimits:
    """Fit fixed limits from complete measurement records for one scope.

    Timestamps are timezone-naive local wall times, as in the measurement
    table. Shift instances must be (shift_id, scheduled local shift start).
    """
    if not isinstance(measurements, pd.DataFrame):
        raise TypeError("measurements must be a pandas DataFrame")
    required = (
        "booth_id", "measurement_point_id", "specification_id",
        "measurement_timestamp", "measurement_id", "shift_instance", "measured_value",
    )
    missing_columns = [column for column in required if column not in measurements.columns]
    if missing_columns:
        raise ValueError(f"missing required columns: {', '.join(missing_columns)}")
    if not measurements.columns.is_unique:
        raise ValueError("measurement columns must be unique")
    if measurements.empty:
        raise ValueError("measurements must not be empty")
    if len(measurements) < 2:
        raise ValueError("at least two measurements are required")

    records = measurements.loc[:, list(required)].copy()
    def local_timestamp(value: object, field: str) -> pd.Timestamp:
        if not isinstance(value, (str, date, datetime, np.datetime64)):
            raise ValueError(f"{field} must contain valid local timestamps")
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field} must contain valid local timestamps") from exc
        if pd.isna(timestamp) or timestamp.tzinfo is not None:
            raise ValueError(f"{field} must contain valid timezone-naive local timestamps")
        return timestamp

    records["measurement_timestamp"] = [
        local_timestamp(value, "measurement_timestamp")
        for value in records["measurement_timestamp"]
    ]

    def valid_id(value: object, maximum: int) -> bool:
        return (
            isinstance(value, Integral)
            and not isinstance(value, (bool, np.bool_))
            and 0 < value <= maximum
        )

    for column in ("booth_id", "measurement_point_id", "specification_id"):
        if not all(valid_id(value, 2147483647) for value in records[column]):
            raise ValueError(f"{column} must contain positive INTEGER values")
        if records[column].nunique() != 1:
            raise ValueError(f"measurements must belong to one scope: multiple {column} values")

    ids = records["measurement_id"]
    if not all(valid_id(value, 9223372036854775807) for value in ids):
        raise ValueError("measurement_id must contain positive BIGINT values")
    if ids.duplicated().any():
        raise ValueError("measurement_id values must be unique")

    shift_keys = []
    for key in records["shift_instance"]:
        if not isinstance(key, tuple) or len(key) != 2 or not valid_id(key[0], 2147483647):
            raise ValueError("shift_instance must be a (positive shift_id, local shift start) tuple")
        shift_keys.append((int(key[0]), local_timestamp(key[1], "shift_instance")))
    records["shift_instance"] = shift_keys

    raw_values = records["measured_value"].tolist()
    validated_values = []
    for value in raw_values:
        if isinstance(value, (str, bytes, bool, np.bool_)):
            raise ValueError("measured_value must contain only numeric values")
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("measured_value must contain only numeric values") from exc
        if not decimal_value.is_finite():
            raise ValueError("measured_value must contain only finite numeric values")
        if abs(decimal_value) > _MEASUREMENT_MAX:
            raise ValueError("measured_value must fit NUMERIC(10,3)")
        try:
            with localcontext() as context:
                context.prec = 32
                if decimal_value != decimal_value.quantize(_MEASUREMENT_QUANTUM):
                    raise ValueError("measured_value must fit NUMERIC(10,3) without rounding")
        except InvalidOperation as exc:
            raise ValueError("measured_value must fit NUMERIC(10,3)") from exc
        validated_values.append(float(decimal_value))
    values = np.asarray(validated_values, dtype="float64")
    records["measured_value"] = values
    records = records.sort_values(["measurement_timestamp", "measurement_id"], kind="mergesort")

    previous_values: dict[tuple[int, pd.Timestamp], float] = {}
    moving_ranges_list: list[float] = []
    with np.errstate(over="ignore", invalid="ignore"):
        for key, value in records[["shift_instance", "measured_value"]].itertuples(
            index=False, name=None
        ):
            if key in previous_values:
                moving_ranges_list.append(abs(value - previous_values[key]))
            previous_values[key] = value
        moving_ranges = np.asarray(moving_ranges_list, dtype="float64")
        if moving_ranges.size == 0:
            raise ValueError("at least one within-shift moving range is required")
        center_line = float(np.mean(values))
        mr_center = float(np.mean(moving_ranges))
        sigma = mr_center / 1.128
        i_lcl = center_line - 3 * sigma
        i_ucl = center_line + 3 * sigma
        mr_ucl = MR_UCL_FACTOR * mr_center

    calculated_values = np.asarray(
        [center_line, mr_center, sigma, i_lcl, i_ucl, mr_ucl],
        dtype="float64",
    )
    if not np.isfinite(moving_ranges).all() or not np.isfinite(
        calculated_values
    ).all():
        raise ValueError("measurements produce non-finite baseline limits")
    for value in calculated_values:
        with localcontext() as context:
            context.prec = 32
            rounded = Decimal(str(value)).quantize(_BASELINE_QUANTUM, rounding=ROUND_HALF_UP)
        if abs(rounded) > _BASELINE_MAX:
            raise ValueError("baseline limits must fit NUMERIC(14,6)")

    return BaselineLimits(
        n_observations=len(values),
        n_valid_mr=len(moving_ranges),
        center_line=center_line,
        sigma=sigma,
        i_lcl=i_lcl,
        i_ucl=i_ucl,
        mr_center=mr_center,
        mr_ucl=mr_ucl,
    )


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
