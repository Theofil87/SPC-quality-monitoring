"""
Synthetic data generator for the SPC & Quality Monitoring project.

Generates CSV files that match the relational model defined in
sql/schema.sql (and are consistent with the reference rows already
inserted by sql/seed.sql), representing six months of tractor cabin
powder-coating production.

Run as a script:

    python -m src.data_generation.generate_data

See docs/data_generation.md for a full explanation of the simulation
design and the assumptions made.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from src.data_generation import config


# ------------------------------------------------------------------
# Static dimension tables (mirrors sql/seed.sql, same row order/ids)
# ------------------------------------------------------------------

def generate_booths() -> pd.DataFrame:
    """Build dim_booth, in the same order sql/seed.sql inserts them."""
    df = pd.DataFrame(config.BOOTHS)
    df.insert(0, "booth_id", range(1, len(df) + 1))
    return df


def generate_track_axes(booths: pd.DataFrame) -> pd.DataFrame:
    """Build dim_track_axis, resolving booth_name -> booth_id."""
    df = pd.DataFrame(config.TRACK_AXES)
    booth_id_map = dict(zip(booths["booth_name"], booths["booth_id"]))
    df["booth_id"] = df["booth_name"].map(booth_id_map)
    df.insert(0, "track_axis_id", range(1, len(df) + 1))
    return df[["track_axis_id", "booth_id", "track_name"]]


def generate_robots(track_axes: pd.DataFrame) -> pd.DataFrame:
    """Build dim_robot, resolving track_name -> track_axis_id."""
    df = pd.DataFrame(config.ROBOTS)
    track_id_map = dict(zip(track_axes["track_name"], track_axes["track_axis_id"]))
    df["track_axis_id"] = df["track_name"].map(track_id_map)
    df["robot_type"] = config.ROBOT_TYPE
    df["status"] = config.ROBOT_STATUS
    df.insert(0, "robot_id", range(1, len(df) + 1))
    return df[["robot_id", "track_axis_id", "robot_name", "robot_type", "status"]]


def generate_shifts() -> pd.DataFrame:
    """Build dim_shift."""
    df = pd.DataFrame(config.SHIFTS)
    df.insert(0, "shift_id", range(1, len(df) + 1))
    return df[["shift_id", "shift_name", "start_time", "end_time"]]


def generate_measurement_points() -> pd.DataFrame:
    """Build dim_measurement_point."""
    df = pd.DataFrame(config.MEASUREMENT_POINTS)
    df.insert(0, "measurement_point_id", range(1, len(df) + 1))
    return df[["measurement_point_id", "point_code", "component", "side", "point_number", "description"]]


def generate_specifications() -> pd.DataFrame:
    """Build dim_specification (a single Coating Thickness characteristic)."""
    df = pd.DataFrame([config.SPECIFICATION])
    df.insert(0, "specification_id", range(1, len(df) + 1))
    return df[["specification_id", "characteristic", "unit", "lsl", "target", "usl"]]


# ------------------------------------------------------------------
# Production calendar (shifts -> batches -> cabins)
# ------------------------------------------------------------------

def _production_dates(start: date, end: date, off_weekday: int) -> list[date]:
    """List every production day between start and end (inclusive)."""
    all_days = pd.date_range(start, end, freq="D")
    return [d.date() for d in all_days if d.weekday() != off_weekday]


def _shift_window(day: date, start_time_str: str, end_time_str: str) -> tuple[datetime, datetime]:
    """Resolve a shift's start/end datetimes for a given production day.

    Handles shifts that cross midnight (e.g. SHIFT_03: 22:00 -> 06:00).
    """
    start_t = time.fromisoformat(start_time_str)
    end_t = time.fromisoformat(end_time_str)
    shift_start = datetime.combine(day, start_t)
    shift_end = datetime.combine(day, end_t)
    if shift_end <= shift_start:
        shift_end += timedelta(days=1)
    return shift_start, shift_end


def generate_batches(shifts: pd.DataFrame) -> pd.DataFrame:
    """Build dim_batch plus the internal booth_name routing per batch.

    Each production day and shift is split into BATCHES_PER_SHIFT equal
    time windows. booth_name is carried along internally (not part of
    dim_batch in the schema) so cabins/measurements can be generated
    consistently; it is dropped before writing dim_batch.csv.
    """
    days = _production_dates(config.START_DATE, config.END_DATE, config.NON_PRODUCTION_WEEKDAY)
    n_batches = config.BATCHES_PER_SHIFT

    rows = []
    for day in days:
        for _, shift in shifts.iterrows():
            shift_start, shift_end = _shift_window(day, shift["start_time"], shift["end_time"])
            batch_duration = (shift_end - shift_start) / n_batches
            for i in range(n_batches):
                batch_start = shift_start + i * batch_duration
                batch_end = batch_start + batch_duration
                booth_name = config.BATCH_BOOTH_PATTERN[i % len(config.BATCH_BOOTH_PATTERN)]
                rows.append(
                    {
                        "shift_id": shift["shift_id"],
                        "batch_start": batch_start,
                        "batch_end": batch_end,
                        "booth_name": booth_name,
                    }
                )

    df = pd.DataFrame(rows)
    df.insert(0, "batch_id", range(1, len(df) + 1))
    return df


def generate_cabins(batches: pd.DataFrame, booths: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Build dim_cabin: CABINS_PER_BATCH cabins per batch, spread across
    the batch's time window."""
    booth_id_map = dict(zip(booths["booth_name"], booths["booth_id"]))
    n_cabins = config.CABINS_PER_BATCH

    rows = []
    cabin_id = 1
    for _, batch in batches.iterrows():
        batch_duration = batch["batch_end"] - batch["batch_start"]
        cabin_spacing = batch_duration / n_cabins
        booth_id = booth_id_map[batch["booth_name"]]
        for i in range(n_cabins):
            # small jitter so cabins are not perfectly evenly spaced
            jitter_seconds = rng.uniform(-30, 30)
            production_timestamp = (
                batch["batch_start"] + i * cabin_spacing + cabin_spacing / 2
                + timedelta(seconds=jitter_seconds)
            )
            rows.append(
                {
                    "cabin_id": cabin_id,
                    "batch_id": batch["batch_id"],
                    "booth_id": booth_id,
                    "booth_name": batch["booth_name"],
                    "production_timestamp": production_timestamp,
                }
            )
            cabin_id += 1

    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Structural effects (measurement point / booth / robot)
# ------------------------------------------------------------------

def generate_point_effects(points: pd.DataFrame, rng: np.random.Generator) -> dict[str, float]:
    """Small, fixed per-measurement-point bias (um)."""
    effects = rng.normal(0.0, config.MEASUREMENT_POINT_EFFECT_STD_UM, size=len(points))
    return dict(zip(points["point_code"], effects))


def generate_robot_effects(robots: pd.DataFrame, rng: np.random.Generator) -> dict[str, float]:
    """Small, fixed per-robot bias (um)."""
    effects = rng.normal(0.0, config.ROBOT_EFFECT_STD_UM, size=len(robots))
    return dict(zip(robots["robot_name"], effects))


def _booth_robot_pool(
    booth_name: str, booths: pd.DataFrame, track_axes: pd.DataFrame, robots: pd.DataFrame
) -> tuple[list[str], list[int]]:
    """The 4 robots belonging to a booth (across both of its track axes),
    in a fixed, deterministic order (sorted by robot_id)."""
    booth_id = booths.loc[booths["booth_name"] == booth_name, "booth_id"].iloc[0]
    track_ids = track_axes.loc[track_axes["booth_id"] == booth_id, "track_axis_id"]
    booth_robots = robots[robots["track_axis_id"].isin(track_ids)].sort_values("robot_id")
    return booth_robots["robot_name"].tolist(), booth_robots["robot_id"].tolist()


# ------------------------------------------------------------------
# Measurements (with special-cause effects applied)
# ------------------------------------------------------------------

def generate_measurements(
    cabins: pd.DataFrame,
    points: pd.DataFrame,
    specifications: pd.DataFrame,
    point_effects: dict[str, float],
    robot_effects: dict[str, float],
    booths: pd.DataFrame,
    robots: pd.DataFrame,
    track_axes: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build fact_quality_measurement and bridge_measurement_robot.

    Applies the stable-process model (target + point effect + booth
    effect + robot effect + noise) to every cabin x measurement point
    combination, then layers the configured special-cause events on
    top for the rows that fall inside their booth/date window.
    """
    spec_id = specifications["specification_id"].iloc[0]
    booth_effect_map = config.BOOTH_EFFECT_UM

    # Cross join: every cabin x every measurement point.
    cabins_key = cabins.assign(_key=1)
    points_key = points.assign(_key=1)
    df = cabins_key.merge(points_key, on="_key").drop(columns="_key")

    n = len(df)
    df["measurement_id"] = range(1, n + 1)
    df["specification_id"] = spec_id
    df["measurement_timestamp"] = df["production_timestamp"]
    df["unit"] = config.SPECIFICATION["unit"]

    # --- stable process components -------------------------------------------------
    point_effect = df["point_code"].map(point_effects).to_numpy()
    booth_effect = df["booth_name"].map(booth_effect_map).to_numpy()

    # Synthetic robot contribution: for each measurement, a random NUMBER
    # of robots (1-4, per config.ROBOT_CONTRIBUTION_COUNT_DISTRIBUTION)
    # is drawn, then that many unique robots are randomly picked out of
    # the 4 belonging to the cabin's booth (may span both track axes).
    # This is not a real physical mapping - see
    # config.ROBOT_CONTRIBUTION_COUNT_DISTRIBUTION.
    pool_size = 4
    possible_counts = np.array(sorted(config.ROBOT_CONTRIBUTION_COUNT_DISTRIBUTION))
    count_probs = np.array([config.ROBOT_CONTRIBUTION_COUNT_DISTRIBUTION[c] for c in possible_counts])

    robot_id_pool = np.empty((n, pool_size), dtype=int)
    robot_effect_pool = np.empty((n, pool_size))
    contributing_count = np.empty(n, dtype=int)

    for booth_name in df["booth_name"].unique():
        mask = (df["booth_name"] == booth_name).to_numpy()
        m = int(mask.sum())
        booth_robot_names, booth_robot_ids = _booth_robot_pool(booth_name, booths, track_axes, robots)
        booth_robot_ids_arr = np.array(booth_robot_ids)
        booth_robot_effects_arr = np.array([robot_effects[name] for name in booth_robot_names])

        # a random permutation of the 4 booth robots per row
        perm = np.argsort(rng.random((m, pool_size)), axis=1)
        robot_id_pool[mask] = booth_robot_ids_arr[perm]
        robot_effect_pool[mask] = booth_robot_effects_arr[perm]
        contributing_count[mask] = rng.choice(possible_counts, size=m, p=count_probs)

    # only the first `contributing_count[i]` columns of each row's random
    # permutation are the robots actually linked to that measurement
    is_contributing = np.arange(pool_size)[None, :] < contributing_count[:, None]
    robot_effect = np.where(is_contributing, robot_effect_pool, np.nan).mean(axis=1, where=is_contributing)

    mean_value = config.PROCESS_MEAN_UM + point_effect + booth_effect + robot_effect
    std_value = np.full(n, config.PROCESS_STD_UM)


    # --- special-cause events -------------------------------------------------------
    event_date = df["measurement_timestamp"].dt.date
    outlier_idx: list[int] = []
    outlier_offset: list[float] = []

    for event in config.SPECIAL_CAUSE_EVENTS:
        booth_mask = (df["booth_name"] == event["booth_name"]).to_numpy()
        date_mask = ((event_date >= event["start_date"]) & (event_date <= event["end_date"])).to_numpy()
        window_mask = booth_mask & date_mask

        if event["event_type"] == "PROCESS_DRIFT":
            span_days = max((event["end_date"] - event["start_date"]).days, 1)
            days_into_window = event_date[window_mask].map(lambda d: (d - event["start_date"]).days).to_numpy()
            fraction = np.clip(days_into_window / span_days, 0.0, 1.0)
            mean_value[window_mask] += fraction * event["drift_total_um"]

        elif event["event_type"] == "PROCESS_SHIFT":
            mean_value[window_mask] += event["shift_amount_um"]

        elif event["event_type"] == "INCREASED_VARIATION":
            std_value[window_mask] = event["inflated_std_um"]

        elif event["event_type"] == "SPECIFICATION_VIOLATION":
            mean_value[window_mask] += event["violation_offset_um"]

        elif event["event_type"] == "OUTLIER":
            candidate_idx = np.flatnonzero(window_mask)
            n_pick = min(event["outlier_count"], len(candidate_idx))
            chosen = rng.choice(candidate_idx, size=n_pick, replace=False)
            outlier_idx.extend(chosen.tolist())
            outlier_offset.extend([event["outlier_magnitude_um"]] * n_pick)

    noise = rng.normal(0.0, 1.0, size=n) * std_value
    measured_value = mean_value + noise

    if outlier_idx:
        measured_value[outlier_idx] = mean_value[outlier_idx] + np.array(outlier_offset)

    measured_value = np.clip(measured_value, a_min=0.0, a_max=None)
    df["measured_value"] = np.round(measured_value, 3)

    measurements = df[
        [
            "measurement_id",
            "cabin_id",
            "measurement_point_id",
            "specification_id",
            "measurement_timestamp",
            "measured_value",
            "unit",
        ]
    ].copy()

    # --- robot bridge table ----------------------------------------------------------
    measurement_ids = df["measurement_id"].to_numpy()
    bridge = pd.DataFrame(
        {
            "measurement_id": np.repeat(measurement_ids, pool_size)[is_contributing.reshape(-1)],
            "robot_id": robot_id_pool.reshape(-1)[is_contributing.reshape(-1)],
        }
    ).sort_values(["measurement_id", "robot_id"]).reset_index(drop=True)

    return measurements, bridge


# ------------------------------------------------------------------
# Ground truth: fact_process_event
# ------------------------------------------------------------------

def generate_process_events(batches: pd.DataFrame, booths: pd.DataFrame) -> pd.DataFrame:
    """Build fact_process_event: one row per affected batch, per event.

    This gives fine-grained ground truth (which batches were affected)
    that SPC detection results can later be compared against.
    """
    booth_id_map = dict(zip(booths["booth_name"], booths["booth_id"]))
    batches = batches.copy()
    batches["batch_date"] = batches["batch_start"].dt.date

    rows = []
    for event in config.SPECIAL_CAUSE_EVENTS:
        affected = batches[
            (batches["booth_name"] == event["booth_name"])
            & (batches["batch_date"] >= event["start_date"])
            & (batches["batch_date"] <= event["end_date"])
        ]
        for _, batch in affected.iterrows():
            rows.append(
                {
                    "event_timestamp": batch["batch_start"],
                    "batch_id": batch["batch_id"],
                    "booth_id": booth_id_map[event["booth_name"]],
                    "event_type": event["event_type"],
                    "description": event["description"],
                    "severity": event["severity"],
                }
            )

    df = pd.DataFrame(rows).sort_values("event_timestamp").reset_index(drop=True)
    df.insert(0, "event_id", range(1, len(df) + 1))
    return df


# ------------------------------------------------------------------
# Orchestration
# ------------------------------------------------------------------

def build_all_tables() -> dict[str, pd.DataFrame]:
    """Generate every table and return them as a dict of DataFrames."""
    rng = np.random.default_rng(config.RANDOM_SEED)

    booths = generate_booths()
    track_axes = generate_track_axes(booths)
    robots = generate_robots(track_axes)
    shifts = generate_shifts()
    points = generate_measurement_points()
    specifications = generate_specifications()

    batches = generate_batches(shifts)
    cabins = generate_cabins(batches, booths, rng)

    point_effects = generate_point_effects(points, rng)
    robot_effects = generate_robot_effects(robots, rng)

    measurements, bridge = generate_measurements(
        cabins, points, specifications, point_effects, robot_effects, booths, robots, track_axes, rng
    )
    process_events = generate_process_events(batches, booths)

    dim_batch = batches[["batch_id", "shift_id", "batch_start", "batch_end"]].copy()
    dim_cabin = cabins[["cabin_id", "batch_id", "booth_id", "production_timestamp"]].copy()

    return {
        "dim_booth": booths,
        "dim_track_axis": track_axes,
        "dim_robot": robots,
        "dim_shift": shifts,
        "dim_batch": dim_batch,
        "dim_cabin": dim_cabin,
        "dim_measurement_point": points,
        "dim_specification": specifications,
        "fact_quality_measurement": measurements,
        "bridge_measurement_robot": bridge,
        "fact_process_event": process_events,
    }


def write_tables(tables: dict[str, pd.DataFrame], output_dir: str = config.OUTPUT_DIR) -> None:
    """Write every table to <output_dir>/<name>.csv."""
    os.makedirs(output_dir, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(os.path.join(output_dir, f"{name}.csv"), index=False)


def validate_generated_data(tables: dict[str, pd.DataFrame]) -> None:
    """Lightweight sanity checks, run right after generation.

    Full validation lives in tests/test_generate_data.py; this is a
    fast smoke check so obvious mistakes fail loudly when generating.
    """
    cabins = tables["dim_cabin"]
    measurements = tables["fact_quality_measurement"]
    points = tables["dim_measurement_point"]

    assert cabins["cabin_id"].is_unique, "duplicate cabin_id"
    assert measurements["measurement_id"].is_unique, "duplicate measurement_id"

    counts_per_cabin = measurements.groupby("cabin_id").size()
    assert (counts_per_cabin == len(points)).all(), "not every cabin has 18 measurements"

    valid_cabin_ids = set(cabins["cabin_id"])
    assert set(measurements["cabin_id"]).issubset(valid_cabin_ids), "invalid cabin_id reference"

    assert (measurements["measured_value"] >= 0).all(), "negative measured_value found"


def main() -> None:
    tables = build_all_tables()
    validate_generated_data(tables)
    write_tables(tables)
    print(f"Generated {len(tables['dim_cabin'])} cabins and {len(tables['fact_quality_measurement'])} measurements.")
    print(f"CSV files written to {config.OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
