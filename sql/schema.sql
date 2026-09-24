-- ============================================================
-- SPC & Quality Monitoring
-- PostgreSQL Database Schema
-- ============================================================

-- ------------------------------------------------------------
-- 1. BOOTHS
-- ------------------------------------------------------------

CREATE TABLE dim_booth (
    booth_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    booth_name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT
);


-- ------------------------------------------------------------
-- 2. TRACK AXES
-- ------------------------------------------------------------

CREATE TABLE dim_track_axis (
    track_axis_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    booth_id INTEGER NOT NULL,
    track_name VARCHAR(50) NOT NULL UNIQUE,

    CONSTRAINT fk_track_booth
        FOREIGN KEY (booth_id)
        REFERENCES dim_booth (booth_id)
);


-- ------------------------------------------------------------
-- 3. ROBOTS
-- ------------------------------------------------------------

CREATE TABLE dim_robot (
    robot_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    track_axis_id INTEGER NOT NULL,
    robot_name VARCHAR(50) NOT NULL UNIQUE,
    robot_type VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL,

    CONSTRAINT fk_robot_track
        FOREIGN KEY (track_axis_id)
        REFERENCES dim_track_axis (track_axis_id),

    CONSTRAINT chk_robot_status
        CHECK (status IN ('ACTIVE', 'INACTIVE', 'MAINTENANCE'))
);


-- ------------------------------------------------------------
-- 4. SHIFTS
-- ------------------------------------------------------------

CREATE TABLE dim_shift (
    shift_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_name VARCHAR(50) NOT NULL UNIQUE,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,

    CONSTRAINT chk_shift_time
        CHECK (start_time <> end_time)
);


-- ------------------------------------------------------------
-- 5. PRODUCTION BATCHES
-- ------------------------------------------------------------

CREATE TABLE dim_batch (
    batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    shift_id INTEGER NOT NULL,
    batch_start TIMESTAMP NOT NULL,
    batch_end TIMESTAMP NOT NULL,

    CONSTRAINT fk_batch_shift
        FOREIGN KEY (shift_id)
        REFERENCES dim_shift (shift_id),

    CONSTRAINT chk_batch_time
        CHECK (batch_end > batch_start)
);


-- ------------------------------------------------------------
-- 6. CABINS
-- ------------------------------------------------------------

CREATE TABLE dim_cabin (
    cabin_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id BIGINT NOT NULL,
    booth_id INTEGER NOT NULL,
    production_timestamp TIMESTAMP NOT NULL,

    CONSTRAINT fk_cabin_batch
        FOREIGN KEY (batch_id)
        REFERENCES dim_batch (batch_id),

    CONSTRAINT fk_cabin_booth
        FOREIGN KEY (booth_id)
        REFERENCES dim_booth (booth_id)
);


-- ------------------------------------------------------------
-- 7. MEASUREMENT POINTS
-- ------------------------------------------------------------

CREATE TABLE dim_measurement_point (
    measurement_point_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    point_code VARCHAR(20) NOT NULL UNIQUE,
    component VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    point_number INTEGER NOT NULL,
    description TEXT,

    CONSTRAINT chk_measurement_side
        CHECK (side IN ('LEFT', 'RIGHT')),

    CONSTRAINT chk_point_number
        CHECK (point_number > 0),

    CONSTRAINT uq_measurement_point
        UNIQUE (component, side, point_number)
);


-- ------------------------------------------------------------
-- 8. SPECIFICATIONS
-- ------------------------------------------------------------

CREATE TABLE dim_specification (
    specification_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    characteristic VARCHAR(100) NOT NULL,
    unit VARCHAR(20) NOT NULL,
    lsl NUMERIC(10,3) NOT NULL,
    target NUMERIC(10,3) NOT NULL,
    usl NUMERIC(10,3) NOT NULL,

    CONSTRAINT chk_specification_limits
        CHECK (lsl < target AND target < usl),

    CONSTRAINT uq_specification
        UNIQUE (characteristic, unit)
);


-- ------------------------------------------------------------
-- 9. QUALITY MEASUREMENTS
-- ------------------------------------------------------------

CREATE TABLE fact_quality_measurement (
    measurement_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    cabin_id BIGINT NOT NULL,
    measurement_point_id INTEGER NOT NULL,
    specification_id INTEGER NOT NULL,

    measurement_timestamp TIMESTAMP NOT NULL,
    measured_value NUMERIC(10,3) NOT NULL,
    unit VARCHAR(20) NOT NULL,

    CONSTRAINT fk_measurement_cabin
        FOREIGN KEY (cabin_id)
        REFERENCES dim_cabin (cabin_id),

    CONSTRAINT fk_measurement_point
        FOREIGN KEY (measurement_point_id)
        REFERENCES dim_measurement_point (measurement_point_id),

    CONSTRAINT fk_measurement_specification
        FOREIGN KEY (specification_id)
        REFERENCES dim_specification (specification_id),

    CONSTRAINT chk_measured_value
        CHECK (measured_value >= 0)
);


-- ------------------------------------------------------------
-- 10. MEASUREMENT TO ROBOT BRIDGE
-- ------------------------------------------------------------

CREATE TABLE bridge_measurement_robot (
    measurement_id BIGINT NOT NULL,
    robot_id INTEGER NOT NULL,

    PRIMARY KEY (measurement_id, robot_id),

    CONSTRAINT fk_bridge_measurement
        FOREIGN KEY (measurement_id)
        REFERENCES fact_quality_measurement (measurement_id),

    CONSTRAINT fk_bridge_robot
        FOREIGN KEY (robot_id)
        REFERENCES dim_robot (robot_id)
);


-- ------------------------------------------------------------
-- 11. PROCESS EVENTS
-- ------------------------------------------------------------

CREATE TABLE fact_process_event (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    event_timestamp TIMESTAMP NOT NULL,
    batch_id BIGINT NOT NULL,
    booth_id INTEGER NOT NULL,

    event_type VARCHAR(50) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL,

    CONSTRAINT fk_event_batch
        FOREIGN KEY (batch_id)
        REFERENCES dim_batch (batch_id),

    CONSTRAINT fk_event_booth
        FOREIGN KEY (booth_id)
        REFERENCES dim_booth (booth_id),

    CONSTRAINT chk_event_type
        CHECK (
            event_type IN (
                'PROCESS_DRIFT',
                'PROCESS_SHIFT',
                'INCREASED_VARIATION',
                'OUTLIER',
                'SPECIFICATION_VIOLATION',
                'EQUIPMENT_EVENT'
            )
        ),

    CONSTRAINT chk_event_severity
        CHECK (
            severity IN ('LOW', 'MEDIUM', 'HIGH')
        )
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX idx_track_axis_booth
    ON dim_track_axis (booth_id);

CREATE INDEX idx_robot_track
    ON dim_robot (track_axis_id);

CREATE INDEX idx_batch_shift
    ON dim_batch (shift_id);

CREATE INDEX idx_cabin_batch
    ON dim_cabin (batch_id);

CREATE INDEX idx_cabin_booth
    ON dim_cabin (booth_id);

CREATE INDEX idx_measurement_cabin
    ON fact_quality_measurement (cabin_id);

CREATE INDEX idx_measurement_point
    ON fact_quality_measurement (measurement_point_id);

CREATE INDEX idx_measurement_timestamp
    ON fact_quality_measurement (measurement_timestamp);

CREATE INDEX idx_measurement_specification
    ON fact_quality_measurement (specification_id);

CREATE INDEX idx_bridge_robot
    ON bridge_measurement_robot (robot_id);

CREATE INDEX idx_event_batch
    ON fact_process_event (batch_id);

CREATE INDEX idx_event_booth
    ON fact_process_event (booth_id);

CREATE INDEX idx_event_timestamp
    ON fact_process_event (event_timestamp);