-- Linked-observation summaries only; links do not define physical point ownership.
SELECT *
FROM v_robot_attribution_quality
ORDER BY booth_name, track_name, robot_name;

-- Bridge cardinality distribution. Counts are per measurement, not production totals.
SELECT
    robot_count,
    count(*) AS measurement_count
FROM (
    SELECT measurement_id, count(*) AS robot_count
    FROM bridge_measurement_robot
    GROUP BY measurement_id
) AS contribution_counts
GROUP BY robot_count
ORDER BY robot_count;