"""
Validation tests for the synthetic SPC & Quality Monitoring dataset.

Runs the generator once (module-scoped) and checks the resulting tables
against the acceptance criteria in the task specification.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data_generation import config
from src.data_generation.generate_data import build_all_tables


@pytest.fixture(scope="module")
def tables():
    return build_all_tables()


@pytest.fixture(scope="module")
def tables_rerun():
    """A second, independent generation run, used for reproducibility checks."""
    return build_all_tables()


# ------------------------------------------------------------------
# 1-3: cabin / measurement volume
# ------------------------------------------------------------------

def test_cabin_count_is_approximately_9360(tables):
    n_cabins = len(tables["dim_cabin"])
    assert 9000 <= n_cabins <= 9500


def test_exactly_18_measurements_per_cabin(tables):
    counts = tables["fact_quality_measurement"].groupby("cabin_id").size()
    assert (counts == 18).all()


def test_total_measurement_count_is_approximately_168480(tables):
    n_measurements = len(tables["fact_quality_measurement"])
    assert 160000 <= n_measurements <= 172000


# ------------------------------------------------------------------
# 4-7: referential integrity
# ------------------------------------------------------------------

def test_all_cabin_foreign_keys_are_valid(tables):
    measurements = tables["fact_quality_measurement"]
    cabins = tables["dim_cabin"]
    batches = tables["dim_batch"]
    booths = tables["dim_booth"]

    assert set(measurements["cabin_id"]).issubset(set(cabins["cabin_id"]))
    assert set(cabins["batch_id"]).issubset(set(batches["batch_id"]))
    assert set(cabins["booth_id"]).issubset(set(booths["booth_id"]))


def test_all_measurement_point_references_are_valid(tables):
    measurements = tables["fact_quality_measurement"]
    points = tables["dim_measurement_point"]
    assert set(measurements["measurement_point_id"]).issubset(set(points["measurement_point_id"]))


def test_all_specification_references_are_valid(tables):
    measurements = tables["fact_quality_measurement"]
    specifications = tables["dim_specification"]
    assert set(measurements["specification_id"]).issubset(set(specifications["specification_id"]))


def test_all_bridge_robot_references_are_valid(tables):
    bridge = tables["bridge_measurement_robot"]
    robots = tables["dim_robot"]
    measurements = tables["fact_quality_measurement"]
    assert set(bridge["robot_id"]).issubset(set(robots["robot_id"]))
    assert set(bridge["measurement_id"]).issubset(set(measurements["measurement_id"]))


# ------------------------------------------------------------------
# Variable robot contribution count (1-4 robots per measurement)
# ------------------------------------------------------------------

def _robot_counts_per_measurement(tables):
    return tables["bridge_measurement_robot"].groupby("measurement_id").size()


def test_every_measurement_has_between_1_and_4_contributing_robots(tables):
    counts = _robot_counts_per_measurement(tables)
    measurements = tables["fact_quality_measurement"]
    # every measurement must appear in the bridge table
    assert set(counts.index) == set(measurements["measurement_id"])
    assert counts.min() >= 1
    assert counts.max() <= 4


def test_no_duplicate_robot_links_per_measurement(tables):
    bridge = tables["bridge_measurement_robot"]
    assert not bridge.duplicated(subset=["measurement_id", "robot_id"]).any()


def test_contributing_robots_belong_to_the_cabin_booth(tables):
    bridge = tables["bridge_measurement_robot"]
    measurements = tables["fact_quality_measurement"]
    cabins = tables["dim_cabin"]
    robots = tables["dim_robot"]
    track_axes = tables["dim_track_axis"]

    merged = (
        bridge.merge(measurements[["measurement_id", "cabin_id"]], on="measurement_id")
        .merge(cabins[["cabin_id", "booth_id"]], on="cabin_id")
        .merge(robots[["robot_id", "track_axis_id"]], on="robot_id")
        .merge(track_axes[["track_axis_id", "booth_id"]], on="track_axis_id", suffixes=("_cabin", "_robot"))
    )
    assert (merged["booth_id_cabin"] == merged["booth_id_robot"]).all()


def test_robot_contribution_count_is_not_fixed(tables):
    counts = _robot_counts_per_measurement(tables)
    assert counts.nunique() > 1


def test_cross_track_robot_contributions_are_possible(tables):
    bridge = tables["bridge_measurement_robot"]
    robots = tables["dim_robot"]
    merged = bridge.merge(robots[["robot_id", "track_axis_id"]], on="robot_id")
    track_axis_spread = merged.groupby("measurement_id")["track_axis_id"].nunique()
    assert (track_axis_spread > 1).any()


# ------------------------------------------------------------------
# 8-10: uniqueness / value sanity
# ------------------------------------------------------------------

def test_no_duplicate_measurement_ids(tables):
    measurements = tables["fact_quality_measurement"]
    assert measurements["measurement_id"].is_unique


def test_no_duplicate_cabin_ids(tables):
    cabins = tables["dim_cabin"]
    assert cabins["cabin_id"].is_unique


def test_all_measured_values_are_non_negative(tables):
    measurements = tables["fact_quality_measurement"]
    assert (measurements["measured_value"] >= 0).all()


# ------------------------------------------------------------------
# 11: stable process centering
# ------------------------------------------------------------------

def test_normal_process_is_centered_around_target(tables):
    measurements = tables["fact_quality_measurement"]
    events = tables["fact_process_event"]

    # exclude measurements produced by batches with a logged special-cause event
    affected_batch_ids = set(events["batch_id"])
    cabins = tables["dim_cabin"]
    affected_cabin_ids = set(cabins.loc[cabins["batch_id"].isin(affected_batch_ids), "cabin_id"])

    stable = measurements[~measurements["cabin_id"].isin(affected_cabin_ids)]
    mean_value = stable["measured_value"].mean()
    assert config.PROCESS_MEAN_UM - 1.0 <= mean_value <= config.PROCESS_MEAN_UM + 1.0


# ------------------------------------------------------------------
# 12: special-cause events are actually represented in measurements
# ------------------------------------------------------------------

def test_special_cause_events_are_represented_in_measurement_data(tables):
    measurements = tables["fact_quality_measurement"]
    cabins = tables["dim_cabin"]
    events = tables["fact_process_event"]

    assert len(events) > 0

    for event_type in ["PROCESS_DRIFT", "PROCESS_SHIFT", "INCREASED_VARIATION", "OUTLIER", "SPECIFICATION_VIOLATION"]:
        assert (events["event_type"] == event_type).any(), f"missing {event_type} in fact_process_event"

    # spec-violation batches must contain values outside [LSL, USL]
    violation_batches = events.loc[events["event_type"] == "SPECIFICATION_VIOLATION", "batch_id"]
    violation_cabins = cabins.loc[cabins["batch_id"].isin(violation_batches), "cabin_id"]
    violation_measurements = measurements[measurements["cabin_id"].isin(violation_cabins)]
    lsl, usl = config.SPECIFICATION["lsl"], config.SPECIFICATION["usl"]
    out_of_spec = violation_measurements[
        (violation_measurements["measured_value"] < lsl) | (violation_measurements["measured_value"] > usl)
    ]
    assert len(out_of_spec) > 0

    # increased-variation batches must show inflated std vs. the stable process
    variation_batches = events.loc[events["event_type"] == "INCREASED_VARIATION", "batch_id"]
    variation_cabins = cabins.loc[cabins["batch_id"].isin(variation_batches), "cabin_id"]
    variation_measurements = measurements[measurements["cabin_id"].isin(variation_cabins)]
    assert variation_measurements["measured_value"].std() > config.PROCESS_STD_UM * 1.5


def test_event_type_check_constraint_values_only(tables):
    allowed = {
        "PROCESS_DRIFT",
        "PROCESS_SHIFT",
        "INCREASED_VARIATION",
        "OUTLIER",
        "SPECIFICATION_VIOLATION",
        "EQUIPMENT_EVENT",
    }
    events = tables["fact_process_event"]
    assert set(events["event_type"]).issubset(allowed)


# ------------------------------------------------------------------
# 13: reproducibility
# ------------------------------------------------------------------

def test_same_seed_produces_reproducible_results(tables, tables_rerun):
    measurements_a = tables["fact_quality_measurement"]
    measurements_b = tables_rerun["fact_quality_measurement"]

    assert len(measurements_a) == len(measurements_b)
    assert np.allclose(
        measurements_a["measured_value"].to_numpy(),
        measurements_b["measured_value"].to_numpy(),
    )

    cabins_a = tables["dim_cabin"]
    cabins_b = tables_rerun["dim_cabin"]
    assert cabins_a.equals(cabins_b)

    bridge_a = tables["bridge_measurement_robot"]
    bridge_b = tables_rerun["bridge_measurement_robot"]
    assert bridge_a.equals(bridge_b)
