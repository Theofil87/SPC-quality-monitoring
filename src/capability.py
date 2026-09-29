"""Classical process capability calculations for measurement streams."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


MOVING_RANGE_D2 = 1.128
DEFAULT_NEAR_ZERO_TOLERANCE = 0.001


def _single_specification_value(data: pd.DataFrame, column: str) -> float | None:
    if column not in data.columns or data.empty:
        return None
    values = pd.to_numeric(data[column], errors="coerce")
    if values.isna().any() or values.nunique(dropna=False) != 1:
        return None
    value = float(values.iloc[0])
    return value if np.isfinite(value) else None


def _sigma_status(
    sigma: float | None,
    observation_count: int,
    *,
    within: bool,
    near_zero_tolerance: float,
) -> str:
    if within and sigma is None:
        return "NO_VALID_MR_PAIR"
    if not within and observation_count < 2:
        return "INSUFFICIENT_OBSERVATIONS"
    if sigma is None:
        return "UNAVAILABLE"
    if sigma == 0:
        return "ZERO_SIGMA"
    if sigma <= near_zero_tolerance:
        return "NEAR_ZERO_SIGMA"
    return "AVAILABLE"


def calculate_capability(
    measurements: pd.DataFrame,
    *,
    near_zero_tolerance: float = DEFAULT_NEAR_ZERO_TOLERANCE,
) -> dict[str, Any]:
    """Summarize one ordered stream and calculate classical capability indices.

    Required measurement columns are ``measurement_id``,
    ``measurement_timestamp``, ``shift_instance``, ``measured_value``,
    ``lsl``, ``target``, ``usl``, and ``spc_signal``. Specification limits
    must be present and consistent across the supplied stream.
    """
    if not np.isfinite(near_zero_tolerance) or near_zero_tolerance < 0:
        raise ValueError("near_zero_tolerance must be a finite non-negative value")

    required_columns = {
        "measurement_id",
        "measurement_timestamp",
        "shift_instance",
        "measured_value",
        "spc_signal",
    }
    missing_columns = required_columns.difference(measurements.columns)
    if missing_columns:
        raise ValueError(f"Missing required measurement columns: {sorted(missing_columns)}")

    result: dict[str, Any] = {
        "booth": None,
        "measurement_point": None,
        "characteristic": None,
        "unit": None,
        "lsl": None,
        "target": None,
        "usl": None,
        "measurement_count": int(len(measurements)),
        "mean": None,
        "median": None,
        "sample_std": None,
        "min": None,
        "max": None,
        "mrbar": None,
        "valid_mr_pairs": 0,
        "d2": MOVING_RANGE_D2,
        "within_sigma": None,
        "overall_sigma": None,
        "within_sigma_status": "NO_VALID_MR_PAIR",
        "overall_sigma_status": "INSUFFICIENT_OBSERVATIONS",
        "specification_status": "MISSING_SPECIFICATION_LIMITS",
        "below_LSL_count": None,
        "above_USL_count": None,
        "OOS_count": None,
        "OOS_rate": None,
        "Cp": None,
        "Cpk": None,
        "Pp": None,
        "Ppk": None,
        "distance_mean_to_LSL": None,
        "distance_mean_to_USL": None,
        "spc_signal_count": 0,
        "spc_signal_rate": None,
        "stability_signal_status": "SPC_SIGNALS_NOT_ASSESSED",
        "availability_status": "UNAVAILABLE",
        "interpretation_status": "EXPLORATORY_PHASE_I",
    }

    for column, output_column in (
        ("booth", "booth"),
        ("measurement_point", "measurement_point"),
        ("characteristic", "characteristic"),
        ("unit", "unit"),
    ):
        if column in measurements.columns and not measurements.empty:
            values = measurements[column].dropna().unique()
            result[output_column] = values[0] if len(values) == 1 else None

    specification_columns = {"lsl", "target", "usl"}
    specification_valid = False
    if not specification_columns.issubset(measurements.columns) or measurements.empty:
        result["specification_status"] = "MISSING_SPECIFICATION_LIMITS"
    elif measurements[list(specification_columns)].isna().any().any():
        result["specification_status"] = "MISSING_SPECIFICATION_LIMITS"
    else:
        lsl = _single_specification_value(measurements, "lsl")
        target = _single_specification_value(measurements, "target")
        usl = _single_specification_value(measurements, "usl")
        specification_valid = (
            lsl is not None
            and target is not None
            and usl is not None
            and lsl < target < usl
        )
        if specification_valid:
            result.update(
                lsl=lsl,
                target=target,
                usl=usl,
                specification_status="AVAILABLE",
            )
        else:
            result["specification_status"] = "INVALID_OR_INCONSISTENT_SPECIFICATION_LIMITS"

    if measurements.empty:
        result["availability_status"] = "UNAVAILABLE"
        result["interpretation_status"] = "EXPLORATORY_PHASE_I_NO_MEASUREMENTS"
        return result

    values = pd.to_numeric(measurements["measured_value"], errors="coerce")
    if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("measured_value must contain only finite numeric values")
    if measurements[["measurement_id", "measurement_timestamp", "shift_instance"]].isna().any().any():
        raise ValueError("measurement_id, measurement_timestamp, and shift_instance cannot be missing")
    if measurements["measurement_id"].duplicated().any():
        raise ValueError("measurement_id must be unique within the capability stream")

    ordered = measurements.assign(_measured_value=values).sort_values(
        ["shift_instance", "measurement_timestamp", "measurement_id"],
        kind="mergesort",
    )
    moving_ranges = ordered.groupby("shift_instance", sort=False)["_measured_value"].diff().abs().dropna()
    result["valid_mr_pairs"] = int(len(moving_ranges))
    if not moving_ranges.empty:
        mrbar = float(moving_ranges.mean())
        result["mrbar"] = mrbar
        result["within_sigma"] = mrbar / MOVING_RANGE_D2

    measurement_count = len(values)
    mean = float(values.mean())
    result.update(
        mean=mean,
        median=float(values.median()),
        min=float(values.min()),
        max=float(values.max()),
        spc_signal_count=int(measurements["spc_signal"].fillna(False).astype(bool).sum()),
    )
    result["spc_signal_rate"] = result["spc_signal_count"] / measurement_count
    result["stability_signal_status"] = (
        "SPC_SIGNALS_PRESENT" if result["spc_signal_count"] else "NO_SPC_SIGNALS_DETECTED"
    )

    overall_sigma = None
    if measurement_count >= 2:
        overall_sigma = float(values.std(ddof=1))
        result.update(sample_std=overall_sigma, overall_sigma=overall_sigma)

    within_sigma = result["within_sigma"]
    result["within_sigma_status"] = _sigma_status(
        within_sigma,
        measurement_count,
        within=True,
        near_zero_tolerance=near_zero_tolerance,
    )
    result["overall_sigma_status"] = _sigma_status(
        overall_sigma,
        measurement_count,
        within=False,
        near_zero_tolerance=near_zero_tolerance,
    )

    if specification_valid:
        below_lsl_count = int((values < lsl).sum())
        above_usl_count = int((values > usl).sum())
        result.update(
            below_LSL_count=below_lsl_count,
            above_USL_count=above_usl_count,
            OOS_count=below_lsl_count + above_usl_count,
            OOS_rate=(below_lsl_count + above_usl_count) / measurement_count,
            distance_mean_to_LSL=mean - lsl,
            distance_mean_to_USL=usl - mean,
        )

    if specification_valid and result["within_sigma_status"] == "AVAILABLE":
        result["Cp"] = (usl - lsl) / (6 * within_sigma)
        result["Cpk"] = min((usl - mean) / (3 * within_sigma), (mean - lsl) / (3 * within_sigma))

    if specification_valid and result["overall_sigma_status"] == "AVAILABLE":
        result["Pp"] = (usl - lsl) / (6 * overall_sigma)
        result["Ppk"] = min(
            (usl - mean) / (3 * overall_sigma),
            (mean - lsl) / (3 * overall_sigma),
        )

    available_indices = sum(result[index] is not None for index in ("Cp", "Cpk", "Pp", "Ppk"))
    if available_indices == 4:
        result["availability_status"] = "AVAILABLE"
    elif available_indices:
        result["availability_status"] = "PARTIALLY_AVAILABLE"

    if result["spc_signal_count"]:
        result["interpretation_status"] = "EXPLORATORY_PHASE_I_SPC_SIGNALS_PRESENT"
    else:
        result["interpretation_status"] = "EXPLORATORY_PHASE_I_STABILITY_NOT_ESTABLISHED"

    return result


def describe_capability_groups(
    measurements: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    """Return descriptive time/group summaries without capability indices."""
    required_columns = {
        "measured_value",
        "below_lsl",
        "above_usl",
        "is_oos",
        "spc_signal",
        *group_columns,
    }
    missing_columns = required_columns.difference(measurements.columns)
    if missing_columns:
        raise ValueError(f"Missing required group-summary columns: {sorted(missing_columns)}")

    summaries = []
    for group_key, group in measurements.groupby(group_columns, dropna=False, sort=True):
        if len(group_columns) == 1:
            group_key = (group_key,)
        summary = dict(zip(group_columns, group_key))
        measurement_count = len(group)
        summary.update(
            measurement_count=measurement_count,
            mean=float(group["measured_value"].mean()),
            median=float(group["measured_value"].median()),
            sample_std=float(group["measured_value"].std(ddof=1)) if measurement_count >= 2 else None,
            min=float(group["measured_value"].min()),
            max=float(group["measured_value"].max()),
            below_LSL_count=int(group["below_lsl"].fillna(False).sum()),
            above_USL_count=int(group["above_usl"].fillna(False).sum()),
            OOS_count=int(group["is_oos"].fillna(False).sum()),
            OOS_rate=float(group["is_oos"].fillna(False).sum() / measurement_count),
            spc_signal_count=int(group["spc_signal"].fillna(False).sum()),
            spc_signal_rate=float(group["spc_signal"].fillna(False).sum() / measurement_count),
        )
        summaries.append(summary)

    return pd.DataFrame(summaries)