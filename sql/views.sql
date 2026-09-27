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