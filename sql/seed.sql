-- ============================================================
-- SPC & Quality Monitoring
-- Reference / Seed Data
-- ============================================================


-- ------------------------------------------------------------
-- 1. BOOTHS
-- ------------------------------------------------------------

INSERT INTO dim_booth (booth_name, description)
VALUES
    ('BOOTH_01', 'Powder coating booth 1'),
    ('BOOTH_02', 'Powder coating booth 2');


-- ------------------------------------------------------------
-- 2. TRACK AXES
-- ------------------------------------------------------------

INSERT INTO dim_track_axis (booth_id, track_name)
SELECT booth_id, 'TRACK_01'
FROM dim_booth
WHERE booth_name = 'BOOTH_01';

INSERT INTO dim_track_axis (booth_id, track_name)
SELECT booth_id, 'TRACK_02'
FROM dim_booth
WHERE booth_name = 'BOOTH_01';

INSERT INTO dim_track_axis (booth_id, track_name)
SELECT booth_id, 'TRACK_03'
FROM dim_booth
WHERE booth_name = 'BOOTH_02';

INSERT INTO dim_track_axis (booth_id, track_name)
SELECT booth_id, 'TRACK_04'
FROM dim_booth
WHERE booth_name = 'BOOTH_02';


-- ------------------------------------------------------------
-- 3. ROBOTS
-- ------------------------------------------------------------

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_01',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_01';

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_02',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_01';

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_03',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_02';

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_04',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_02';

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_05',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_03';

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_06',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_03';

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_07',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_04';

INSERT INTO dim_robot (
    track_axis_id,
    robot_name,
    robot_type,
    status
)
SELECT
    track_axis_id,
    'ROBOT_08',
    'ABB 6-axis powder coating robot',
    'ACTIVE'
FROM dim_track_axis
WHERE track_name = 'TRACK_04';


-- ------------------------------------------------------------
-- 4. SHIFTS
-- ------------------------------------------------------------

INSERT INTO dim_shift (
    shift_name,
    start_time,
    end_time
)
VALUES
    ('SHIFT_01', '06:00', '14:00'),
    ('SHIFT_02', '14:00', '22:00'),
    ('SHIFT_03', '22:00', '06:00');


-- ------------------------------------------------------------
-- 5. MEASUREMENT POINTS
-- ------------------------------------------------------------

INSERT INTO dim_measurement_point (
    point_code,
    component,
    side,
    point_number,
    description
)
VALUES
    ('A-L1', 'A_PILLAR', 'LEFT',  1, 'A pillar measurement point 1'),
    ('A-L2', 'A_PILLAR', 'LEFT',  2, 'A pillar measurement point 2'),
    ('A-L3', 'A_PILLAR', 'LEFT',  3, 'A pillar measurement point 3'),

    ('A-R1', 'A_PILLAR', 'RIGHT', 1, 'A pillar measurement point 1'),
    ('A-R2', 'A_PILLAR', 'RIGHT', 2, 'A pillar measurement point 2'),
    ('A-R3', 'A_PILLAR', 'RIGHT', 3, 'A pillar measurement point 3'),

    ('B-L1', 'B_PILLAR', 'LEFT',  1, 'B pillar measurement point 1'),
    ('B-L2', 'B_PILLAR', 'LEFT',  2, 'B pillar measurement point 2'),
    ('B-L3', 'B_PILLAR', 'LEFT',  3, 'B pillar measurement point 3'),

    ('B-R1', 'B_PILLAR', 'RIGHT', 1, 'B pillar measurement point 1'),
    ('B-R2', 'B_PILLAR', 'RIGHT', 2, 'B pillar measurement point 2'),
    ('B-R3', 'B_PILLAR', 'RIGHT', 3, 'B pillar measurement point 3'),

    ('T-L1', 'UPPER_CONNECTING_ELEMENT', 'LEFT',  1, 'Upper connecting element left'),
    ('T-R1', 'UPPER_CONNECTING_ELEMENT', 'RIGHT', 1, 'Upper connecting element right'),

    ('C-L1', 'A_B_CONNECTING_ELEMENT', 'LEFT',  1, 'A-B connecting element left 1'),
    ('C-L2', 'A_B_CONNECTING_ELEMENT', 'LEFT',  2, 'A-B connecting element left 2'),
    ('C-R1', 'A_B_CONNECTING_ELEMENT', 'RIGHT', 1, 'A-B connecting element right 1'),
    ('C-R2', 'A_B_CONNECTING_ELEMENT', 'RIGHT', 2, 'A-B connecting element right 2');


-- ------------------------------------------------------------
-- 6. SPECIFICATION
-- ------------------------------------------------------------

INSERT INTO dim_specification (
    characteristic,
    unit,
    lsl,
    target,
    usl
)
VALUES
    ('Coating Thickness', 'um', 70.000, 75.000, 80.000);