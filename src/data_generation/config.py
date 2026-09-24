"""
Configuration for the synthetic SPC & Quality Monitoring dataset generator.

All manufacturing assumptions that are NOT explicitly stated in the task
specification are collected here (and clearly marked as "ASSUMPTION") so
they are easy to find, review, and change.

The database structure itself (table/column names) is defined in
sql/schema.sql and is NOT reproduced or altered here - this file only
holds the parameters needed to generate CSV data that fits that schema.
"""

from __future__ import annotations

from datetime import date

# ------------------------------------------------------------------
# Reproducibility
# ------------------------------------------------------------------

RANDOM_SEED = 42

# ------------------------------------------------------------------
# Production period
# ------------------------------------------------------------------

START_DATE = date(2026, 1, 1)
END_DATE = date(2026, 6, 30)

# ASSUMPTION: "6 production days per week" -> one fixed weekday is a
# non-production day. Python weekday(): Monday=0 ... Sunday=6.
NON_PRODUCTION_WEEKDAY = 6  # Sunday

# ------------------------------------------------------------------
# Shifts / batches / cabins
# ------------------------------------------------------------------

SHIFTS = [
    {"shift_name": "SHIFT_01", "start_time": "06:00:00", "end_time": "14:00:00"},
    {"shift_name": "SHIFT_02", "start_time": "14:00:00", "end_time": "22:00:00"},
    {"shift_name": "SHIFT_03", "start_time": "22:00:00", "end_time": "06:00:00"},
]

BATCHES_PER_SHIFT = 4
CABINS_PER_BATCH = 5

# ASSUMPTION: a batch (group of 5 cabins moving together) is routed as a
# whole through one booth. Within a shift, batches alternate evenly
# between the two booths (2 batches -> BOOTH_01, 2 batches -> BOOTH_02).
BATCH_BOOTH_PATTERN = ["BOOTH_01", "BOOTH_01", "BOOTH_02", "BOOTH_02"]

# ------------------------------------------------------------------
# Equipment layout (booths / tracks / robots)
# ------------------------------------------------------------------

BOOTHS = [
    {"booth_name": "BOOTH_01", "description": "Powder coating booth 1"},
    {"booth_name": "BOOTH_02", "description": "Powder coating booth 2"},
]

TRACK_AXES = [
    {"track_name": "TRACK_01", "booth_name": "BOOTH_01"},
    {"track_name": "TRACK_02", "booth_name": "BOOTH_01"},
    {"track_name": "TRACK_03", "booth_name": "BOOTH_02"},
    {"track_name": "TRACK_04", "booth_name": "BOOTH_02"},
]

ROBOTS = [
    {"robot_name": "ROBOT_01", "track_name": "TRACK_01"},
    {"robot_name": "ROBOT_02", "track_name": "TRACK_01"},
    {"robot_name": "ROBOT_03", "track_name": "TRACK_02"},
    {"robot_name": "ROBOT_04", "track_name": "TRACK_02"},
    {"robot_name": "ROBOT_05", "track_name": "TRACK_03"},
    {"robot_name": "ROBOT_06", "track_name": "TRACK_03"},
    {"robot_name": "ROBOT_07", "track_name": "TRACK_04"},
    {"robot_name": "ROBOT_08", "track_name": "TRACK_04"},
]
ROBOT_TYPE = "ABB 6-axis powder coating robot"
ROBOT_STATUS = "ACTIVE"

# ASSUMPTION: the real robot-to-measurement-point mapping is unknown and
# is NOT modeled. All 4 robots in a booth operate on a cabin
# simultaneously, and any measurement point may plausibly be influenced
# by any of them. For the synthetic dataset, each measurement's
# contributing robots are therefore a reproducible RANDOM sample of
# ASSUMPTION: the real robot-to-measurement-point mapping is unknown and
# is NOT modeled. All 4 robots in a booth operate on a cabin
# simultaneously, and a given measurement point may plausibly be
# influenced by just one of them, or by several. For the synthetic
# dataset, each measurement's contributing robot COUNT is drawn from
# ROBOT_CONTRIBUTION_COUNT_DISTRIBUTION (keys = possible robot counts,
# values = probability weights, must sum to 1.0), and that many unique
# robots are then drawn at random from the 4 robots belonging to the
# cabin's booth (which may come from the same or different track axes).
# The measurement point's side/component never determines the count or
# the choice of robots. This is a synthetic contribution assignment for
# bridge_measurement_robot, not a representation of the true physical
# robot-to-point relationship.
ROBOT_CONTRIBUTION_COUNT_DISTRIBUTION = {1: 0.15, 2: 0.45, 3: 0.30, 4: 0.10}


# ------------------------------------------------------------------
# Measurement points (must match sql/seed.sql exactly, same order)
# ------------------------------------------------------------------

MEASUREMENT_POINTS = [
    {"point_code": "A-L1", "component": "A_PILLAR", "side": "LEFT", "point_number": 1, "description": "A pillar measurement point 1"},
    {"point_code": "A-L2", "component": "A_PILLAR", "side": "LEFT", "point_number": 2, "description": "A pillar measurement point 2"},
    {"point_code": "A-L3", "component": "A_PILLAR", "side": "LEFT", "point_number": 3, "description": "A pillar measurement point 3"},
    {"point_code": "A-R1", "component": "A_PILLAR", "side": "RIGHT", "point_number": 1, "description": "A pillar measurement point 1"},
    {"point_code": "A-R2", "component": "A_PILLAR", "side": "RIGHT", "point_number": 2, "description": "A pillar measurement point 2"},
    {"point_code": "A-R3", "component": "A_PILLAR", "side": "RIGHT", "point_number": 3, "description": "A pillar measurement point 3"},
    {"point_code": "B-L1", "component": "B_PILLAR", "side": "LEFT", "point_number": 1, "description": "B pillar measurement point 1"},
    {"point_code": "B-L2", "component": "B_PILLAR", "side": "LEFT", "point_number": 2, "description": "B pillar measurement point 2"},
    {"point_code": "B-L3", "component": "B_PILLAR", "side": "LEFT", "point_number": 3, "description": "B pillar measurement point 3"},
    {"point_code": "B-R1", "component": "B_PILLAR", "side": "RIGHT", "point_number": 1, "description": "B pillar measurement point 1"},
    {"point_code": "B-R2", "component": "B_PILLAR", "side": "RIGHT", "point_number": 2, "description": "B pillar measurement point 2"},
    {"point_code": "B-R3", "component": "B_PILLAR", "side": "RIGHT", "point_number": 3, "description": "B pillar measurement point 3"},
    {"point_code": "T-L1", "component": "UPPER_CONNECTING_ELEMENT", "side": "LEFT", "point_number": 1, "description": "Upper connecting element left"},
    {"point_code": "T-R1", "component": "UPPER_CONNECTING_ELEMENT", "side": "RIGHT", "point_number": 1, "description": "Upper connecting element right"},
    {"point_code": "C-L1", "component": "A_B_CONNECTING_ELEMENT", "side": "LEFT", "point_number": 1, "description": "A-B connecting element left 1"},
    {"point_code": "C-L2", "component": "A_B_CONNECTING_ELEMENT", "side": "LEFT", "point_number": 2, "description": "A-B connecting element left 2"},
    {"point_code": "C-R1", "component": "A_B_CONNECTING_ELEMENT", "side": "RIGHT", "point_number": 1, "description": "A-B connecting element right 1"},
    {"point_code": "C-R2", "component": "A_B_CONNECTING_ELEMENT", "side": "RIGHT", "point_number": 2, "description": "A-B connecting element right 2"},
]

# ------------------------------------------------------------------
# Specification / quality characteristic
# ------------------------------------------------------------------

SPECIFICATION = {
    "characteristic": "Coating Thickness",
    "unit": "um",
    "lsl": 70.0,
    "target": 75.0,
    "usl": 80.0,
}

# ------------------------------------------------------------------
# Stable-process model parameters
# ------------------------------------------------------------------

PROCESS_MEAN_UM = 75.0
PROCESS_STD_UM = 1.2

# ASSUMPTION: small, fixed structural effects layered on top of the
# stable process mean. Kept well inside the specification range
# (70-80 um) so the process still looks "in control" most of the time.
MEASUREMENT_POINT_EFFECT_STD_UM = 0.3
BOOTH_EFFECT_UM = {"BOOTH_01": -0.2, "BOOTH_02": 0.2}
ROBOT_EFFECT_STD_UM = 0.25

# ------------------------------------------------------------------
# Special-cause events (ground truth for fact_process_event)
# ------------------------------------------------------------------
# ASSUMPTION: event windows and magnitudes below are hand-picked so that
# they are spread realistically across the six-month period, are not
# perfectly aligned with calendar boundaries, and stay subtle enough
# that SPC analysis - not the event log - has to (re)discover them.
#
# event_type must be one of the values allowed by chk_event_type in
# sql/schema.sql. "STABLE_PROCESS" is intentionally NOT a row in
# fact_process_event (it is not part of that CHECK constraint); stable
# behavior is simply the absence of a special-cause event.

SPECIAL_CAUSE_EVENTS = [
    {
        "event_type": "PROCESS_DRIFT",
        "booth_name": "BOOTH_01",
        "start_date": date(2026, 2, 2),
        "end_date": date(2026, 2, 13),
        "severity": "MEDIUM",
        "description": "Gradual upward drift of coating thickness mean in Booth 1",
        "drift_total_um": 2.5,
    },
    {
        "event_type": "PROCESS_SHIFT",
        "booth_name": "BOOTH_02",
        "start_date": date(2026, 3, 9),
        "end_date": date(2026, 3, 20),
        "severity": "HIGH",
        "description": "Sudden downward shift of coating thickness mean in Booth 2",
        "shift_amount_um": -2.2,
    },
    {
        "event_type": "INCREASED_VARIATION",
        "booth_name": "BOOTH_01",
        "start_date": date(2026, 4, 6),
        "end_date": date(2026, 4, 17),
        "severity": "MEDIUM",
        "description": "Elevated coating thickness variation in Booth 1",
        "inflated_std_um": 3.0,
    },
    {
        "event_type": "SPECIFICATION_VIOLATION",
        "booth_name": "BOOTH_02",
        "start_date": date(2026, 5, 4),
        "end_date": date(2026, 5, 5),
        "severity": "HIGH",
        "description": "Cluster of below-LSL coating thickness readings in Booth 2",
        "violation_offset_um": -7.0,
    },
    {
        "event_type": "SPECIFICATION_VIOLATION",
        "booth_name": "BOOTH_01",
        "start_date": date(2026, 6, 15),
        "end_date": date(2026, 6, 15),
        "severity": "HIGH",
        "description": "Cluster of above-USL coating thickness readings in Booth 1",
        "violation_offset_um": 6.5,
    },
    {
        "event_type": "OUTLIER",
        "booth_name": "BOOTH_01",
        "start_date": date(2026, 1, 20),
        "end_date": date(2026, 1, 20),
        "severity": "LOW",
        "description": "Isolated extreme coating thickness reading(s) in Booth 1",
        "outlier_count": 3,
        "outlier_magnitude_um": 9.0,
    },
    {
        "event_type": "OUTLIER",
        "booth_name": "BOOTH_02",
        "start_date": date(2026, 2, 25),
        "end_date": date(2026, 2, 25),
        "severity": "LOW",
        "description": "Isolated extreme coating thickness reading(s) in Booth 2",
        "outlier_count": 3,
        "outlier_magnitude_um": -8.5,
    },
    {
        "event_type": "OUTLIER",
        "booth_name": "BOOTH_02",
        "start_date": date(2026, 4, 29),
        "end_date": date(2026, 4, 29),
        "severity": "LOW",
        "description": "Isolated extreme coating thickness reading(s) in Booth 2",
        "outlier_count": 4,
        "outlier_magnitude_um": 8.0,
    },
    {
        "event_type": "OUTLIER",
        "booth_name": "BOOTH_01",
        "start_date": date(2026, 6, 3),
        "end_date": date(2026, 6, 3),
        "severity": "LOW",
        "description": "Isolated extreme coating thickness reading(s) in Booth 1",
        "outlier_count": 3,
        "outlier_magnitude_um": -9.5,
    },
]

# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------

OUTPUT_DIR = "data/raw"
