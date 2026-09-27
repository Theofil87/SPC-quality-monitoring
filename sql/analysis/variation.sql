-- Batch summaries in production order; descriptive variation, not SPC rules.
SELECT
    batch_id,
    booth_name,
    shift_name,
    production_date,
    mean_thickness,
    stddev_thickness,
    min_thickness,
    max_thickness
FROM v_batch_quality
ORDER BY production_date, batch_id;

-- Compare within-cabin and between-cabin variation by booth and point.
SELECT
    measurement.booth_name,
    measurement.point_code,
    count(*) AS measurement_count,
    avg(measurement.measured_value) AS mean_thickness,
    stddev_samp(measurement.measured_value) AS overall_sample_stddev,
    avg(cabin_quality.stddev_thickness) AS mean_within_cabin_stddev
FROM v_measurement_enriched AS measurement
JOIN v_cabin_quality AS cabin_quality
    ON cabin_quality.cabin_id = measurement.cabin_id
GROUP BY measurement.booth_name, measurement.point_code
ORDER BY measurement.booth_name, measurement.point_code;

-- Shift variation in production order, independent of booth/point grouping.
SELECT
    production_date,
    shift_name,
    measurement_count,
    mean_thickness,
    stddev_thickness,
    min_thickness,
    max_thickness
FROM v_shift_quality_daily
ORDER BY production_date, shift_name;

-- Measurement-point variation across the whole run, independent of booth.
SELECT
    point_code,
    component,
    side,
    measurement_count,
    mean_thickness,
    stddev_thickness,
    mean_deviation_from_target,
    min_thickness,
    max_thickness
FROM v_measurement_point_quality
ORDER BY component, side, point_number;