"""Descriptive drift and shift-to-shift diagnostics for measurement streams.

The functions here intentionally consume precomputed SPC flags. They never
detect SPC signals, read process-event labels, or calculate capability indices.
"""

from __future__ import annotations

from statistics import NormalDist
from typing import Any, Iterable

import numpy as np
import pandas as pd


_REQUIRED_COLUMNS = {
    "measurement_id", "measurement_timestamp", "production_month",
    "shift_instance", "shift_id", "shift_name", "measured_value", "target",
    "below_lsl", "above_usl", "is_oos", "spc_signal",
}


def _validated_measurements(measurements: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize the one-row-per-measurement analysis input."""
    missing = _REQUIRED_COLUMNS.difference(measurements.columns)
    if missing:
        raise ValueError(f"Missing required measurement columns: {sorted(missing)}")
    if measurements.empty:
        raise ValueError("measurements cannot be empty")
    if measurements["measurement_id"].isna().any() or measurements["measurement_id"].duplicated().any():
        raise ValueError("measurement_id must be present and unique")

    data = measurements.copy()
    for column in ("measurement_timestamp", "production_month", "shift_instance"):
        data[column] = pd.to_datetime(data[column], errors="coerce")
        if data[column].isna().any():
            raise ValueError(f"{column} must contain valid timestamps")
    if data[["shift_id", "shift_name"]].isna().any().any():
        raise ValueError("shift_id and shift_name cannot be missing")
    mapping_counts = data.groupby("shift_instance", dropna=False).agg(
        shift_ids=("shift_id", "nunique"), shift_names=("shift_name", "nunique")
    )
    if (mapping_counts[["shift_ids", "shift_names"]] != 1).any().any():
        raise ValueError("each shift_instance must map to one shift_id and shift_name")

    for column in ("measured_value", "target"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
        if data[column].isna().any() or not np.isfinite(data[column].to_numpy(dtype=float)).all():
            raise ValueError(f"{column} must contain only finite numeric values")
    return data


def _group_summary(data: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, group in data.groupby(group_columns, sort=True, dropna=False):
        if len(group_columns) == 1:
            key = (key,)
        count = len(group)
        values = group["measured_value"].astype(float)
        row = dict(zip(group_columns, key))
        row.update(
            measurement_count=count,
            mean=float(values.mean()),
            sample_std=float(values.std(ddof=1)) if count >= 2 else None,
            mean_deviation_from_target=float((values - group["target"].astype(float)).mean()),
            below_lsl_count=int(group["below_lsl"].fillna(False).astype(bool).sum()),
            above_usl_count=int(group["above_usl"].fillna(False).astype(bool).sum()),
            oos_count=int(group["is_oos"].fillna(False).astype(bool).sum()),
            oos_rate=float(group["is_oos"].fillna(False).astype(bool).mean()),
            spc_signal_count=int(group["spc_signal"].fillna(False).astype(bool).sum()),
            spc_signal_rate=float(group["spc_signal"].fillna(False).astype(bool).mean()),
        )
        for rule in ("rule_1", "rule_2", "rule_3", "rule_4"):
            if rule in group:
                row[f"{rule}_count"] = int(group[rule].fillna(False).astype(bool).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_drift_shift_inputs(measurements: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return monthly, actual-shift-instance, and shift-type summaries."""
    data = _validated_measurements(measurements)
    monthly = _group_summary(data, ["production_month"])
    shift_instance = _group_summary(data, ["shift_instance", "shift_id", "shift_name"])
    timing = data.groupby("shift_instance", as_index=False).agg(
        first_measurement_timestamp=("measurement_timestamp", "min"),
        last_measurement_timestamp=("measurement_timestamp", "max"),
    )
    shift_instance = shift_instance.merge(timing, on="shift_instance", validate="one_to_one")
    shift_instance["within_sum_of_squares"] = (
        shift_instance["sample_std"].fillna(0.0) ** 2
        * (shift_instance["measurement_count"] - 1).clip(lower=0)
    )
    shift_type = _group_summary(data, ["shift_id", "shift_name"])
    instances = data.groupby(["shift_id", "shift_name"], as_index=False)["shift_instance"].nunique()
    instances = instances.rename(columns={"shift_instance": "shift_instance_count"})
    shift_type = shift_type.merge(instances, on=["shift_id", "shift_name"], validate="one_to_one")
    return {
        "monthly": monthly.sort_values("production_month", kind="mergesort").reset_index(drop=True),
        "shift_instance": shift_instance.sort_values("shift_instance", kind="mergesort").reset_index(drop=True),
        "shift_type": shift_type.sort_values(["shift_id", "shift_name"], kind="mergesort").reset_index(drop=True),
    }


def calculate_variation_decomposition(measurements: pd.DataFrame) -> dict[str, Any]:
    """Partition total SS into within- and between-actual-shift components."""
    data = _validated_measurements(measurements)
    values = data["measured_value"].to_numpy(dtype=float)
    overall_mean = float(values.mean())
    total_ss = float(np.square(values - overall_mean).sum())
    grouped = data.groupby("shift_instance", sort=True)["measured_value"]
    group_counts = grouped.count()
    group_means = grouped.mean()
    within_ss = float(grouped.apply(lambda x: np.square(x.to_numpy(dtype=float) - x.mean()).sum()).sum())
    between_ss = float((group_counts * np.square(group_means - overall_mean)).sum())
    group_count = int(len(group_counts))
    observation_count = int(len(data))
    return {
        "measurement_count": observation_count,
        "shift_instance_count": group_count,
        "overall_mean": overall_mean,
        "total_sum_of_squares": total_ss,
        "within_shift_sum_of_squares": within_ss,
        "between_shift_sum_of_squares": between_ss,
        "within_shift_share": within_ss / total_ss if total_ss else None,
        "between_shift_share": between_ss / total_ss if total_ss else None,
        "pooled_within_shift_sd": float(np.sqrt(within_ss / (observation_count - group_count)))
        if observation_count > group_count else None,
        "overall_sample_sd": float(np.std(values, ddof=1)) if observation_count >= 2 else None,
        "shift_instance_mean_distribution": group_means.rename("mean").reset_index(),
        "subgroup_size_distribution": group_counts.value_counts().sort_index().rename_axis("measurement_count").reset_index(name="shift_instance_count"),
    }


def calculate_rolling_shift_instance_means(
    shift_instance_summary: pd.DataFrame,
    windows: Iterable[int] = (7, 14, 21),
) -> pd.DataFrame:
    """Attach trailing rolling means to chronological actual-shift means."""
    required = {"shift_instance", "mean"}
    missing = required.difference(shift_instance_summary.columns)
    if missing:
        raise ValueError(f"Missing shift-summary columns: {sorted(missing)}")
    data = shift_instance_summary.copy()
    data["shift_instance"] = pd.to_datetime(data["shift_instance"], errors="coerce")
    data["mean"] = pd.to_numeric(data["mean"], errors="coerce")
    if data["shift_instance"].isna().any() or data["mean"].isna().any():
        raise ValueError("shift_instance and mean must be valid")
    if data["shift_instance"].duplicated().any():
        raise ValueError("shift_instance summary must have one row per shift_instance")
    data = data.sort_values("shift_instance", kind="mergesort").reset_index(drop=True)
    for window in windows:
        if not isinstance(window, int) or window < 1:
            raise ValueError("rolling windows must be positive integers")
        data[f"rolling_mean_{window}"] = data["mean"].rolling(window=window, min_periods=window).mean()
    return data


def first_half_second_half_comparison(shift_instance_summary: pd.DataFrame) -> dict[str, Any]:
    """Compare chronological halves; for odd N, the later half receives the middle instance."""
    ordered = calculate_rolling_shift_instance_means(shift_instance_summary, windows=())
    count = len(ordered)
    if count < 2:
        raise ValueError("at least two shift instances are required")
    split = count // 2
    first, second = ordered.iloc[:split], ordered.iloc[split:]
    return {
        "first_half_shift_instance_count": int(len(first)),
        "second_half_shift_instance_count": int(len(second)),
        "first_half_mean": float(first["mean"].mean()),
        "second_half_mean": float(second["mean"].mean()),
        "second_minus_first_mean": float(second["mean"].mean() - first["mean"].mean()),
        "first_half_sample_std": float(first["mean"].std(ddof=1)) if len(first) >= 2 else None,
        "second_half_sample_std": float(second["mean"].std(ddof=1)) if len(second) >= 2 else None,
        "first_half_start": first["shift_instance"].iloc[0],
        "first_half_end": first["shift_instance"].iloc[-1],
        "second_half_start": second["shift_instance"].iloc[0],
        "second_half_end": second["shift_instance"].iloc[-1],
    }


def calculate_trend_diagnostics(shift_instance_summary: pd.DataFrame) -> dict[str, Any]:
    """Fit OLS to chronological shift means and report observational diagnostics.

    The confidence interval is a normal-approximation 95% interval. It is not
    an autocorrelation-adjusted causal or production-monitoring inference.
    """
    ordered = calculate_rolling_shift_instance_means(shift_instance_summary, windows=())
    if len(ordered) < 3:
        raise ValueError("at least three shift instances are required for trend diagnostics")
    start = ordered["shift_instance"].iloc[0]
    elapsed_days = (ordered["shift_instance"] - start).dt.total_seconds().to_numpy(dtype=float) / 86400.0
    x = elapsed_days - elapsed_days.mean()
    y = ordered["mean"].to_numpy(dtype=float)
    ss_x = float(np.square(x).sum())
    if ss_x == 0:
        raise ValueError("shift_instance timestamps must vary for trend diagnostics")
    slope = float(np.dot(x, y - y.mean()) / ss_x)
    intercept_at_center = float(y.mean())
    fitted = intercept_at_center + slope * x
    residuals = y - fitted
    residual_ss = float(np.square(residuals).sum())
    slope_standard_error = float(np.sqrt((residual_ss / (len(y) - 2)) / ss_x))
    z_975 = NormalDist().inv_cdf(0.975)
    ci_low, ci_high = slope - z_975 * slope_standard_error, slope + z_975 * slope_standard_error
    loo_slopes = []
    for index in range(len(y)):
        keep = np.arange(len(y)) != index
        x_keep, y_keep = x[keep], y[keep]
        loo_slopes.append(float(np.dot(x_keep, y_keep - y_keep.mean()) / np.square(x_keep).sum()))
    duration_days = float(elapsed_days.max() - elapsed_days.min())
    return {
        "trend_unit": "actual_shift_instance_mean",
        "observation_count": int(len(y)),
        "time_origin": start,
        "duration_days": duration_days,
        "slope_per_day": slope,
        "slope_standard_error": slope_standard_error,
        "slope_ci_95_low": float(ci_low),
        "slope_ci_95_high": float(ci_high),
        "confidence_interval_method": "normal_approximation_95_percent",
        "estimated_cumulative_fitted_change": float(slope * duration_days),
        "fitted_values": fitted,
        "residuals": residuals,
        "leave_one_shift_out_slope_min": float(min(loo_slopes)),
        "leave_one_shift_out_slope_max": float(max(loo_slopes)),
        "max_leave_one_shift_out_slope_change": float(max(abs(value - slope) for value in loo_slopes)),
        "slope_direction_stable_under_leave_one_out": bool(min(loo_slopes) > 0 or max(loo_slopes) < 0),
        "observational_caveat": "Trend diagnostics describe association with time; they do not establish drift or cause.",
    }
