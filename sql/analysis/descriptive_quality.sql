-- Overall measurement-level distribution.
SELECT
    count(*) AS measurement_count,
    avg(measured_value) AS mean_thickness,
    stddev_samp(measured_value) AS stddev_thickness,
    min(measured_value) AS min_thickness,
    max(measured_value) AS max_thickness
FROM v_measurement_enriched;

-- Compare booth and point subgroups without joining the robot bridge.
SELECT
    booth_name,
    point_code,
    count(*) AS measurement_count,
    avg(measured_value) AS mean_thickness,
    stddev_samp(measured_value) AS stddev_thickness,
    min(measured_value) AS min_thickness,
    max(measured_value) AS max_thickness
FROM v_measurement_enriched
GROUP BY booth_name, point_code
ORDER BY booth_name, point_code;