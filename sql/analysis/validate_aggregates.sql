-- Each query below must return zero rows to pass (grain/fanout checks for
-- the descriptive analysis views). Reference totals: 167400 measurements,
-- 9300 cabins, 1860 batches, 233 process events, 393409 bridge links.

-- 1. Measurement-level aggregate views must partition all measurements exactly once.
SELECT view_name, total
FROM (
    SELECT 'v_production_volume' AS view_name, sum(measurement_count) AS total FROM v_production_volume
    UNION ALL SELECT 'v_cabin_quality', sum(measurement_count) FROM v_cabin_quality
    UNION ALL SELECT 'v_batch_quality', sum(measurement_count) FROM v_batch_quality
    UNION ALL SELECT 'v_booth_quality_daily', sum(measurement_count) FROM v_booth_quality_daily
    UNION ALL SELECT 'v_shift_quality_daily', sum(measurement_count) FROM v_shift_quality_daily
    UNION ALL SELECT 'v_measurement_point_quality', sum(measurement_count) FROM v_measurement_point_quality
) AS totals
WHERE total <> (SELECT count(*) FROM fact_quality_measurement);

-- 2. Row counts must equal distinct dimension keys (no duplicate/missing groups).
SELECT 'v_cabin_quality' AS view_name, count(*) AS row_count, (SELECT count(*) FROM dim_cabin) AS expected
FROM v_cabin_quality
HAVING count(*) <> (SELECT count(*) FROM dim_cabin)
UNION ALL
SELECT 'v_batch_quality', count(*), (SELECT count(*) FROM dim_batch)
FROM v_batch_quality
HAVING count(*) <> (SELECT count(*) FROM dim_batch)
UNION ALL
SELECT 'v_measurement_point_quality', count(*), (SELECT count(*) FROM dim_measurement_point)
FROM v_measurement_point_quality
HAVING count(*) <> (SELECT count(*) FROM dim_measurement_point);

-- 3. Each measurement point covers every cabin exactly once (9300 per point).
SELECT point_code, measurement_count
FROM v_measurement_point_quality
WHERE measurement_count <> (SELECT count(*) FROM dim_cabin);

-- 4. Event-evaluation join must stay 1:1 with fact_process_event (no batch fanout).
SELECT
    (SELECT count(*) FROM fact_process_event) AS event_row_count,
    (SELECT count(*) FROM v_event_evaluation_context) AS view_row_count
WHERE (SELECT count(*) FROM fact_process_event)
   <> (SELECT count(*) FROM v_event_evaluation_context);

-- 5. Robot attribution is bridge-grain, not measurement-grain: confirm the
-- expected fanout equals total bridge links, not the 167400 measurement count.
SELECT
    (SELECT sum(linked_measurement_count) FROM v_robot_attribution_quality) AS summed_linked_measurements,
    (SELECT count(*) FROM bridge_measurement_robot) AS bridge_row_count
WHERE (SELECT sum(linked_measurement_count) FROM v_robot_attribution_quality)
   <> (SELECT count(*) FROM bridge_measurement_robot);

-- 6. Confirm robot linkage stays within the documented 1-4 contributors per
-- measurement; a violation here would explain any unexpected fanout above.
SELECT measurement_id, count(*) AS robot_count
FROM bridge_measurement_robot
GROUP BY measurement_id
HAVING count(*) NOT BETWEEN 1 AND 4;
