-- Each query below must return zero rows / matching counts to pass.

-- 1. Row-count parity between the fact table and the view.
SELECT
    (SELECT count(*) FROM fact_quality_measurement) AS fact_row_count,
    (SELECT count(*) FROM v_measurement_enriched) AS view_row_count
WHERE (SELECT count(*) FROM fact_quality_measurement)
   <> (SELECT count(*) FROM v_measurement_enriched);

-- 2. measurement_id must be unique in the view.
SELECT measurement_id, count(*)
FROM v_measurement_enriched
GROUP BY measurement_id
HAVING count(*) > 1;

-- 3. No measurement is lost or fabricated (anti-join in both directions).
SELECT fact.measurement_id
FROM fact_quality_measurement AS fact
LEFT JOIN v_measurement_enriched AS view USING (measurement_id)
WHERE view.measurement_id IS NULL

UNION ALL

SELECT view.measurement_id
FROM v_measurement_enriched AS view
LEFT JOIN fact_quality_measurement AS fact USING (measurement_id)
WHERE fact.measurement_id IS NULL;

-- 4. OOS counts must agree with a direct fact-table calculation.
SELECT
    (SELECT count(*) FROM v_measurement_enriched WHERE is_oos) AS view_oos_count,
    (
        SELECT count(*)
        FROM fact_quality_measurement AS fact
        JOIN dim_specification AS specification USING (specification_id)
        WHERE fact.measured_value < specification.lsl
           OR fact.measured_value > specification.usl
    ) AS direct_oos_count
WHERE (SELECT count(*) FROM v_measurement_enriched WHERE is_oos)
   <> (
        SELECT count(*)
        FROM fact_quality_measurement AS fact
        JOIN dim_specification AS specification USING (specification_id)
        WHERE fact.measured_value < specification.lsl
           OR fact.measured_value > specification.usl
    );
