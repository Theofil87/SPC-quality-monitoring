CREATE OR REPLACE VIEW v_measurement_enriched AS
SELECT
    measurement.measurement_id,
    measurement.cabin_id,
    cabin.batch_id,
    batch.shift_id,
    batch.batch_start,
    batch.batch_end,
    shift.shift_name,
    cabin.booth_id,
    booth.booth_name,
    cabin.production_timestamp::date AS production_date,
    cabin.production_timestamp,
    measurement.measurement_timestamp,
    measurement.measurement_point_id,
    point.point_code,
    point.component,
    point.side,
    point.point_number,
    measurement.specification_id,
    specification.characteristic,
    measurement.measured_value,
    measurement.unit,
    specification.lsl,
    specification.target,
    specification.usl,
    measurement.measured_value - specification.target AS deviation_from_target,
    measurement.measured_value < specification.lsl AS below_lsl,
    measurement.measured_value > specification.usl AS above_usl,
    measurement.measured_value < specification.lsl
        OR measurement.measured_value > specification.usl AS is_oos,
    CASE
        WHEN measurement.measured_value < specification.lsl THEN 'BELOW_LSL'
        WHEN measurement.measured_value > specification.usl THEN 'ABOVE_USL'
        ELSE 'IN_SPEC'
    END AS compliance_status
FROM fact_quality_measurement AS measurement
JOIN dim_cabin AS cabin USING (cabin_id)
JOIN dim_batch AS batch USING (batch_id)
JOIN dim_shift AS shift USING (shift_id)
JOIN dim_booth AS booth USING (booth_id)
JOIN dim_measurement_point AS point USING (measurement_point_id)
JOIN dim_specification AS specification USING (specification_id);

CREATE OR REPLACE VIEW v_spc_rule_results_booth01_a_l1 AS
WITH source AS (
    SELECT
        measurement.measurement_id,
        measurement.booth_id,
        measurement.booth_name,
        measurement.measurement_point_id,
        measurement.point_code,
        measurement.specification_id,
        measurement.shift_id,
        measurement.shift_name,
        measurement.batch_start,
        measurement.measurement_timestamp,
        measurement.measured_value,
        (
            (measurement.batch_start::date + shift.start_time)
            - CASE
                WHEN shift.end_time <= shift.start_time
                 AND measurement.batch_start::time < shift.start_time
                    THEN interval '1 day'
                ELSE interval '0 day'
              END
        ) AS shift_instance_start
    FROM v_measurement_enriched AS measurement
    JOIN dim_shift AS shift USING (shift_id)
    WHERE measurement.booth_name = 'BOOTH_01'
      AND measurement.point_code = 'A-L1'
), ordered AS (
    SELECT
        source.*,
        row_number() OVER stream_order AS observation_number,
        lag(measured_value) OVER stream_order AS previous_value
    FROM source
    WINDOW stream_order AS (
        PARTITION BY
            booth_id,
            measurement_point_id,
            specification_id,
            shift_id,
            shift_instance_start
        ORDER BY measurement_timestamp, measurement_id
    )
), moving_ranges AS (
    SELECT
        ordered.*,
        CASE
            WHEN previous_value IS NULL THEN NULL
            ELSE abs(measured_value - previous_value)
        END AS moving_range
    FROM ordered
), baseline AS (
    SELECT
        booth_id,
        measurement_point_id,
        specification_id,
        avg(measured_value) AS center_line,
        avg(moving_range) / 1.128 AS sigma
    FROM moving_ranges
    GROUP BY booth_id, measurement_point_id, specification_id
), zoned AS (
    SELECT
        moving_ranges.*,
        baseline.center_line,
        baseline.sigma,
        baseline.center_line - 3 * baseline.sigma AS lcl,
        baseline.center_line + 3 * baseline.sigma AS ucl,
        CASE WHEN moving_ranges.measured_value > baseline.center_line THEN 1
             WHEN moving_ranges.measured_value < baseline.center_line THEN -1
             ELSE 0
        END AS center_line_side,
        CASE WHEN moving_ranges.measured_value > baseline.center_line + 2 * baseline.sigma THEN 1 ELSE 0 END AS above_2_sigma,
        CASE WHEN moving_ranges.measured_value < baseline.center_line - 2 * baseline.sigma THEN 1 ELSE 0 END AS below_2_sigma,
        CASE WHEN moving_ranges.measured_value > baseline.center_line + baseline.sigma THEN 1 ELSE 0 END AS above_1_sigma,
        CASE WHEN moving_ranges.measured_value < baseline.center_line - baseline.sigma THEN 1 ELSE 0 END AS below_1_sigma
    FROM moving_ranges
    JOIN baseline USING (booth_id, measurement_point_id, specification_id)
), rule_windows AS (
    SELECT
        zoned.*,
        sum(above_2_sigma) OVER shift_order_3 AS above_2_in_3,
        sum(below_2_sigma) OVER shift_order_3 AS below_2_in_3,
        sum(above_1_sigma) OVER shift_order_5 AS above_1_in_5,
        sum(below_1_sigma) OVER shift_order_5 AS below_1_in_5,
        lag(center_line_side, 1, 0) OVER shift_order AS previous_center_line_side
    FROM zoned
    WINDOW
        shift_order AS (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start
            ORDER BY measurement_timestamp, measurement_id
        ),
        shift_order_3 AS (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start
            ORDER BY measurement_timestamp, measurement_id
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ),
        shift_order_5 AS (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start
            ORDER BY measurement_timestamp, measurement_id
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        )
), rule_runs AS (
    SELECT
        rule_windows.*,
        sum(CASE WHEN center_line_side <> previous_center_line_side THEN 1 ELSE 0 END)
            OVER (
                PARTITION BY
                    booth_id,
                    measurement_point_id,
                    specification_id,
                    shift_id,
                    shift_instance_start
                ORDER BY measurement_timestamp, measurement_id
            ) AS center_line_run_id
    FROM rule_windows
), rule_run_lengths AS (
    SELECT
        rule_runs.*,
        count(*) OVER (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start,
                center_line_run_id
            ORDER BY measurement_timestamp, measurement_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS center_line_run_length
    FROM rule_runs
), signals AS (
    SELECT
        rule_run_lengths.*,
        (measured_value > ucl OR measured_value < lcl) AS rule_1,
        (observation_number >= 3 AND (above_2_in_3 >= 2 OR below_2_in_3 >= 2)) AS rule_2,
        (observation_number >= 5 AND (above_1_in_5 >= 4 OR below_1_in_5 >= 4)) AS rule_3,
        (center_line_side <> 0 AND center_line_run_length >= 8) AS rule_4
    FROM rule_run_lengths
)
SELECT
    measurement_timestamp,
    measurement_id,
    booth_name AS booth,
    point_code AS measurement_point,
    shift_id,
    shift_name,
    shift_instance_start AS shift_instance,
    measured_value,
    moving_range,
    center_line,
    sigma,
    lcl,
    ucl,
    rule_1,
    rule_2,
    rule_3,
    rule_4,
    (rule_1 OR rule_2 OR rule_3 OR rule_4) AS spc_signal
FROM signals;

CREATE OR REPLACE VIEW v_production_volume AS
SELECT
    production_date,
    shift_id,
    shift_name,
    booth_id,
    booth_name,
    count(DISTINCT batch_id) AS batch_count,
    count(DISTINCT cabin_id) AS cabin_count,
    count(*) AS measurement_count
FROM v_measurement_enriched
GROUP BY production_date, shift_id, shift_name, booth_id, booth_name;

CREATE OR REPLACE VIEW v_cabin_quality AS
SELECT
    cabin_id,
    batch_id,
    booth_id,
    booth_name,
    shift_id,
    shift_name,
    production_date,
    count(*) AS measurement_count,
    avg(measured_value) AS mean_thickness,
    stddev_samp(measured_value) AS stddev_thickness,
    min(measured_value) AS min_thickness,
    max(measured_value) AS max_thickness,
    count(*) FILTER (WHERE is_oos) AS oos_count,
    count(*) FILTER (WHERE is_oos)::numeric / nullif(count(*), 0) AS oos_rate,
    avg(deviation_from_target) AS mean_deviation_from_target
FROM v_measurement_enriched
GROUP BY cabin_id, batch_id, booth_id, booth_name, shift_id, shift_name, production_date;

CREATE OR REPLACE VIEW v_batch_quality AS
SELECT
    batch_id,
    booth_id,
    booth_name,
    shift_id,
    shift_name,
    production_date,
    min(batch_start) AS batch_start,
    max(batch_end) AS batch_end,
    min(production_timestamp) AS first_cabin_timestamp,
    max(production_timestamp) AS last_cabin_timestamp,
    count(DISTINCT cabin_id) AS cabin_count,
    count(*) AS measurement_count,
    avg(measured_value) AS mean_thickness,
    stddev_samp(measured_value) AS stddev_thickness,
    min(measured_value) AS min_thickness,
    max(measured_value) AS max_thickness,
    count(*) FILTER (WHERE is_oos) AS oos_count,
    count(*) FILTER (WHERE is_oos)::numeric / nullif(count(*), 0) AS oos_rate,
    avg(deviation_from_target) AS mean_deviation_from_target
FROM v_measurement_enriched
GROUP BY batch_id, booth_id, booth_name, shift_id, shift_name, production_date;

CREATE OR REPLACE VIEW v_booth_quality_daily AS
SELECT
    production_date,
    booth_id,
    booth_name,
    count(DISTINCT batch_id) AS batch_count,
    count(DISTINCT cabin_id) AS cabin_count,
    count(*) AS measurement_count,
    avg(measured_value) AS mean_thickness,
    stddev_samp(measured_value) AS stddev_thickness,
    min(measured_value) AS min_thickness,
    max(measured_value) AS max_thickness,
    count(*) FILTER (WHERE is_oos) AS oos_count,
    count(*) FILTER (WHERE is_oos)::numeric / nullif(count(*), 0) AS oos_rate,
    avg(deviation_from_target) AS mean_deviation_from_target
FROM v_measurement_enriched
GROUP BY production_date, booth_id, booth_name;

CREATE OR REPLACE VIEW v_shift_quality_daily AS
SELECT
    production_date,
    shift_id,
    shift_name,
    count(DISTINCT batch_id) AS batch_count,
    count(DISTINCT cabin_id) AS cabin_count,
    count(*) AS measurement_count,
    avg(measured_value) AS mean_thickness,
    stddev_samp(measured_value) AS stddev_thickness,
    min(measured_value) AS min_thickness,
    max(measured_value) AS max_thickness,
    count(*) FILTER (WHERE is_oos) AS oos_count,
    count(*) FILTER (WHERE is_oos)::numeric / nullif(count(*), 0) AS oos_rate,
    avg(deviation_from_target) AS mean_deviation_from_target
FROM v_measurement_enriched
GROUP BY production_date, shift_id, shift_name;

CREATE OR REPLACE VIEW v_measurement_point_quality AS
SELECT
    measurement_point_id,
    point_code,
    component,
    side,
    point_number,
    count(*) AS measurement_count,
    avg(measured_value) AS mean_thickness,
    stddev_samp(measured_value) AS stddev_thickness,
    min(measured_value) AS min_thickness,
    max(measured_value) AS max_thickness,
    count(*) FILTER (WHERE is_oos) AS oos_count,
    count(*) FILTER (WHERE is_oos)::numeric / nullif(count(*), 0) AS oos_rate,
    avg(deviation_from_target) AS mean_deviation_from_target
FROM v_measurement_enriched
GROUP BY measurement_point_id, point_code, component, side, point_number;

-- Attribution only: robot links are synthetic and do not encode point ownership.
CREATE OR REPLACE VIEW v_robot_attribution_quality AS
SELECT
    robot.robot_id,
    robot.robot_name,
    axis.track_axis_id,
    axis.track_name,
    booth.booth_id,
    booth.booth_name,
    count(DISTINCT measurement.measurement_id) AS linked_measurement_count,
    count(DISTINCT measurement.cabin_id) AS linked_cabin_count,
    avg(measurement.measured_value) AS linked_mean_thickness,
    stddev_samp(measurement.measured_value) AS linked_stddev_thickness,
    min(measurement.measured_value) AS linked_min_thickness,
    max(measurement.measured_value) AS linked_max_thickness,
    count(DISTINCT measurement.measurement_id) FILTER (WHERE measurement.is_oos) AS linked_oos_count,
    count(DISTINCT measurement.measurement_id) FILTER (WHERE measurement.is_oos)::numeric
        / nullif(count(DISTINCT measurement.measurement_id), 0) AS linked_oos_rate,
    avg(measurement.deviation_from_target) AS linked_mean_deviation_from_target
FROM bridge_measurement_robot AS bridge
JOIN dim_robot AS robot USING (robot_id)
JOIN dim_track_axis AS axis USING (track_axis_id)
JOIN dim_booth AS booth USING (booth_id)
JOIN v_measurement_enriched AS measurement USING (measurement_id)
GROUP BY robot.robot_id, robot.robot_name, axis.track_axis_id, axis.track_name, booth.booth_id, booth.booth_name;

-- One row per event record/batch. This view is for retrospective evaluation,
-- never as an input to SPC detection logic.
CREATE OR REPLACE VIEW v_event_evaluation_context AS
SELECT
    event.event_id,
    event.event_timestamp,
    event.event_type,
    event.description,
    event.severity,
    event.batch_id,
    event.booth_id,
    booth.booth_name,
    batch_quality.cabin_count,
    batch_quality.measurement_count,
    batch_quality.mean_thickness,
    batch_quality.stddev_thickness,
    batch_quality.oos_count,
    batch_quality.oos_rate
FROM fact_process_event AS event
JOIN dim_booth AS booth USING (booth_id)
JOIN v_batch_quality AS batch_quality USING (batch_id);