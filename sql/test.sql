SELECT 'booths' AS table_name, COUNT(*) AS row_count
FROM dim_booth

UNION ALL

SELECT 'track_axes', COUNT(*)
FROM dim_track_axis

UNION ALL

SELECT 'robots', COUNT(*)
FROM dim_robot

UNION ALL

SELECT 'shifts', COUNT(*)
FROM dim_shift

UNION ALL

SELECT 'measurement_points', COUNT(*)
FROM dim_measurement_point

UNION ALL

SELECT 'specifications', COUNT(*)
FROM dim_specification;