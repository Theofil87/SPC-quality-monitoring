-- Canonical clean load for generated CSVs only.
-- Apply schema.sql first. Do not run seed.sql in this database.
-- Run psql with its working directory set to the generated CSV directory,
-- for example: psql -X -v ON_ERROR_STOP=1 -d DATABASE -f ../../sql/load.sql

\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM dim_booth)
       OR EXISTS (SELECT 1 FROM dim_track_axis)
       OR EXISTS (SELECT 1 FROM dim_robot)
       OR EXISTS (SELECT 1 FROM dim_shift)
       OR EXISTS (SELECT 1 FROM dim_batch)
       OR EXISTS (SELECT 1 FROM dim_cabin)
       OR EXISTS (SELECT 1 FROM dim_measurement_point)
       OR EXISTS (SELECT 1 FROM dim_specification)
       OR EXISTS (SELECT 1 FROM fact_quality_measurement)
       OR EXISTS (SELECT 1 FROM bridge_measurement_robot)
       OR EXISTS (SELECT 1 FROM fact_process_event) THEN
        RAISE EXCEPTION 'Canonical CSV load requires empty tables; do not mix with seed.sql or an existing dataset';
    END IF;
END
$$;

CREATE TEMP TABLE stg_dim_booth AS SELECT * FROM dim_booth WITH NO DATA;
CREATE TEMP TABLE stg_dim_track_axis AS SELECT * FROM dim_track_axis WITH NO DATA;
CREATE TEMP TABLE stg_dim_robot AS SELECT * FROM dim_robot WITH NO DATA;
CREATE TEMP TABLE stg_dim_shift AS SELECT * FROM dim_shift WITH NO DATA;
CREATE TEMP TABLE stg_dim_batch AS SELECT * FROM dim_batch WITH NO DATA;
CREATE TEMP TABLE stg_dim_cabin AS SELECT * FROM dim_cabin WITH NO DATA;
CREATE TEMP TABLE stg_dim_measurement_point AS SELECT * FROM dim_measurement_point WITH NO DATA;
CREATE TEMP TABLE stg_dim_specification AS SELECT * FROM dim_specification WITH NO DATA;
CREATE TEMP TABLE stg_fact_quality_measurement AS SELECT * FROM fact_quality_measurement WITH NO DATA;
CREATE TEMP TABLE stg_bridge_measurement_robot AS SELECT * FROM bridge_measurement_robot WITH NO DATA;
CREATE TEMP TABLE stg_fact_process_event AS SELECT * FROM fact_process_event WITH NO DATA;

\copy stg_dim_booth FROM 'dim_booth.csv' WITH (FORMAT csv, HEADER true)
\copy stg_dim_track_axis FROM 'dim_track_axis.csv' WITH (FORMAT csv, HEADER true)
\copy stg_dim_robot FROM 'dim_robot.csv' WITH (FORMAT csv, HEADER true)
\copy stg_dim_shift FROM 'dim_shift.csv' WITH (FORMAT csv, HEADER true)
\copy stg_dim_batch FROM 'dim_batch.csv' WITH (FORMAT csv, HEADER true)
\copy stg_dim_cabin FROM 'dim_cabin.csv' WITH (FORMAT csv, HEADER true)
\copy stg_dim_measurement_point FROM 'dim_measurement_point.csv' WITH (FORMAT csv, HEADER true)
\copy stg_dim_specification FROM 'dim_specification.csv' WITH (FORMAT csv, HEADER true)
\copy stg_fact_quality_measurement FROM 'fact_quality_measurement.csv' WITH (FORMAT csv, HEADER true)
\copy stg_bridge_measurement_robot FROM 'bridge_measurement_robot.csv' WITH (FORMAT csv, HEADER true)
\copy stg_fact_process_event FROM 'fact_process_event.csv' WITH (FORMAT csv, HEADER true)

INSERT INTO dim_booth OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_booth;
INSERT INTO dim_track_axis OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_track_axis;
INSERT INTO dim_robot OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_robot;
INSERT INTO dim_shift OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_shift;
INSERT INTO dim_batch OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_batch;
INSERT INTO dim_cabin OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_cabin;
INSERT INTO dim_measurement_point OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_measurement_point;
INSERT INTO dim_specification OVERRIDING SYSTEM VALUE SELECT * FROM stg_dim_specification;
INSERT INTO fact_quality_measurement OVERRIDING SYSTEM VALUE SELECT * FROM stg_fact_quality_measurement;
INSERT INTO bridge_measurement_robot SELECT * FROM stg_bridge_measurement_robot;
INSERT INTO fact_process_event OVERRIDING SYSTEM VALUE SELECT * FROM stg_fact_process_event;

DO $$
DECLARE
    sequence_target RECORD;
    sequence_name TEXT;
    max_value BIGINT;
BEGIN
    FOR sequence_target IN
        SELECT *
        FROM (VALUES
            ('dim_booth', 'booth_id'),
            ('dim_track_axis', 'track_axis_id'),
            ('dim_robot', 'robot_id'),
            ('dim_shift', 'shift_id'),
            ('dim_batch', 'batch_id'),
            ('dim_cabin', 'cabin_id'),
            ('dim_measurement_point', 'measurement_point_id'),
            ('dim_specification', 'specification_id'),
            ('fact_quality_measurement', 'measurement_id'),
            ('fact_process_event', 'event_id')
        ) AS sequence_targets(table_name, column_name)
    LOOP
        EXECUTE format('SELECT max(%I) FROM %I', sequence_target.column_name, sequence_target.table_name)
            INTO max_value;
        sequence_name := pg_get_serial_sequence(sequence_target.table_name, sequence_target.column_name);
        PERFORM setval(sequence_name::regclass, COALESCE(max_value, 1), max_value IS NOT NULL);
    END LOOP;
END
$$;

-- Compares staged CSV row counts with the rows committed to target tables,
-- then checks relational and generator-specific invariants.
\ir test.sql

COMMIT;