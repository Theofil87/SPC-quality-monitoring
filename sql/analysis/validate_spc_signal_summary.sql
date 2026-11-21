\set ON_ERROR_STOP on

DO $validation$
BEGIN
    IF EXISTS (
-- Every query below must return zero rows to pass.

-- 1. Every eligible source measurement appears exactly once in the SPC view.
WITH eligible AS (
    SELECT measurement_id
    FROM v_measurement_enriched
    WHERE booth_name = 'BOOTH_01'
      AND point_code = 'A-L1'
), results AS (
    SELECT measurement_id
    FROM v_spc_rule_results_booth01_a_l1
)
SELECT
    (SELECT count(*) FROM eligible) AS eligible_count,
    (SELECT count(*) FROM results) AS result_count,
    (SELECT count(DISTINCT measurement_id) FROM results) AS distinct_result_count
WHERE (SELECT count(*) FROM eligible) <> (SELECT count(*) FROM results)
   OR (SELECT count(*) FROM results) <> (SELECT count(DISTINCT measurement_id) FROM results)
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 1 failed';
    END IF;
END
$validation$;

DO $validation$
BEGIN
    IF EXISTS (
-- 2. No eligible measurements are missing and no unexpected IDs are present.
WITH spc_source AS MATERIALIZED (
    SELECT * FROM v_spc_rule_results_booth01_a_l1
)
SELECT eligible.measurement_id
FROM v_measurement_enriched AS eligible
LEFT JOIN spc_source AS results USING (measurement_id)
WHERE eligible.booth_name = 'BOOTH_01'
  AND eligible.point_code = 'A-L1'
  AND results.measurement_id IS NULL
UNION ALL
SELECT results.measurement_id
FROM spc_source AS results
LEFT JOIN v_measurement_enriched AS eligible USING (measurement_id)
WHERE eligible.measurement_id IS NULL
   OR eligible.booth_name <> 'BOOTH_01'
   OR eligible.point_code <> 'A-L1'
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 2 failed';
    END IF;
END
$validation$;

DO $validation$
BEGIN
    IF EXISTS (
-- 3. The stored overall flag must equal the OR of Rule 1-4 for every row.
SELECT measurement_id, spc_signal, (rule_1 OR rule_2 OR rule_3 OR rule_4) AS rule_or
FROM v_spc_rule_results_booth01_a_l1
WHERE (baseline_id IS NOT NULL AND spc_signal IS DISTINCT FROM (rule_1 OR rule_2 OR rule_3 OR rule_4))
   OR (baseline_id IS NULL AND (spc_signal IS NOT NULL OR rule_1 OR rule_2 OR rule_3 OR rule_4))
   OR spc_evaluation_status IS DISTINCT FROM
        CASE WHEN baseline_id IS NULL THEN 'NOT_EVALUATED' ELSE 'EVALUATED' END
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 3 failed';
    END IF;
END
$validation$;

DO $validation$
BEGIN
    IF EXISTS (
-- 4. Overall signal count is distinct-measurement based and cannot exceed total.
WITH counts AS (
    SELECT
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE spc_signal) AS signal_measurements,
        count(DISTINCT measurement_id) FILTER (
            WHERE rule_1 OR rule_2 OR rule_3 OR rule_4
        ) AS rule_or_measurements
    FROM v_spc_rule_results_booth01_a_l1
)
SELECT *
FROM counts
WHERE signal_measurements > total_measurements
   OR signal_measurements <> rule_or_measurements
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 4 failed';
    END IF;
END
$validation$;

DO $validation$
BEGIN
    IF EXISTS (
-- 5. Monthly totals, OOS counts, and each rule count reconcile overall.
WITH spc_source AS MATERIALIZED (
    SELECT * FROM v_spc_rule_results_booth01_a_l1
), base AS (
    SELECT
        spc.measurement_id,
        date_trunc('month', measurement.production_timestamp)::date AS production_month,
        measurement.is_oos,
        spc.rule_1,
        spc.rule_2,
        spc.rule_3,
        spc.rule_4,
        (spc.rule_1 OR spc.rule_2 OR spc.rule_3 OR spc.rule_4) AS any_rule_signal
    FROM spc_source AS spc
    JOIN v_measurement_enriched AS measurement USING (measurement_id)
), overall AS (
    SELECT
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_measurements
    FROM base
), monthly AS (
    SELECT
        production_month,
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_measurements
    FROM base
    GROUP BY production_month
), monthly_totals AS (
    SELECT
        sum(total_measurements) AS total_measurements,
        sum(signal_measurements) AS signal_measurements,
        sum(oos_measurements) AS oos_measurements,
        sum(rule_1_measurements) AS rule_1_measurements,
        sum(rule_2_measurements) AS rule_2_measurements,
        sum(rule_3_measurements) AS rule_3_measurements,
        sum(rule_4_measurements) AS rule_4_measurements
    FROM monthly
)
SELECT overall.*, monthly_totals.*
FROM overall
CROSS JOIN monthly_totals
WHERE overall.total_measurements <> monthly_totals.total_measurements
   OR overall.signal_measurements <> monthly_totals.signal_measurements
   OR overall.oos_measurements <> monthly_totals.oos_measurements
   OR overall.rule_1_measurements <> monthly_totals.rule_1_measurements
   OR overall.rule_2_measurements <> monthly_totals.rule_2_measurements
   OR overall.rule_3_measurements <> monthly_totals.rule_3_measurements
   OR overall.rule_4_measurements <> monthly_totals.rule_4_measurements
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 5 failed';
    END IF;
END
$validation$;

DO $validation$
BEGIN
    IF EXISTS (
-- 6. Actual shift-instance totals, OOS counts, and each rule count reconcile.
WITH spc_source AS MATERIALIZED (
    SELECT * FROM v_spc_rule_results_booth01_a_l1
), base AS (
    SELECT
        spc.measurement_id,
        spc.shift_instance,
        spc.shift_id,
        spc.shift_name,
        measurement.is_oos,
        spc.rule_1,
        spc.rule_2,
        spc.rule_3,
        spc.rule_4,
        (spc.rule_1 OR spc.rule_2 OR spc.rule_3 OR spc.rule_4) AS any_rule_signal
    FROM spc_source AS spc
    JOIN v_measurement_enriched AS measurement USING (measurement_id)
), overall AS (
    SELECT
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_measurements
    FROM base
), shifts AS (
    SELECT
        shift_instance,
        shift_id,
        shift_name,
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_measurements
    FROM base
    GROUP BY shift_instance, shift_id, shift_name
), shift_totals AS (
    SELECT
        sum(total_measurements) AS total_measurements,
        sum(signal_measurements) AS signal_measurements,
        sum(oos_measurements) AS oos_measurements,
        sum(rule_1_measurements) AS rule_1_measurements,
        sum(rule_2_measurements) AS rule_2_measurements,
        sum(rule_3_measurements) AS rule_3_measurements,
        sum(rule_4_measurements) AS rule_4_measurements
    FROM shifts
)
SELECT overall.*, shift_totals.*
FROM overall
CROSS JOIN shift_totals
WHERE overall.total_measurements <> shift_totals.total_measurements
   OR overall.signal_measurements <> shift_totals.signal_measurements
   OR overall.oos_measurements <> shift_totals.oos_measurements
   OR overall.rule_1_measurements <> shift_totals.rule_1_measurements
   OR overall.rule_2_measurements <> shift_totals.rule_2_measurements
   OR overall.rule_3_measurements <> shift_totals.rule_3_measurements
   OR overall.rule_4_measurements <> shift_totals.rule_4_measurements
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 6 failed';
    END IF;
END
$validation$;

DO $validation$
BEGIN
    IF EXISTS (
-- 7. OOS totals are unchanged by SPC status and agree with enriched source data.
WITH spc_source AS MATERIALIZED (
    SELECT * FROM v_spc_rule_results_booth01_a_l1
), summary_oos AS (
    SELECT count(DISTINCT measurement_id) FILTER (WHERE measurement.is_oos) AS oos_measurements
    FROM spc_source AS spc
    JOIN v_measurement_enriched AS measurement USING (measurement_id)
), source_oos AS (
    SELECT count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements
    FROM v_measurement_enriched
    WHERE booth_name = 'BOOTH_01'
      AND point_code = 'A-L1'
)
SELECT summary_oos.oos_measurements AS summary_oos_measurements,
       source_oos.oos_measurements AS source_oos_measurements
FROM summary_oos
CROSS JOIN source_oos
WHERE summary_oos.oos_measurements <> source_oos.oos_measurements
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 7 failed';
    END IF;
END
$validation$;

DO $validation$
BEGIN
    IF EXISTS (
-- 8. Each actual shift instance maps to one shift type; do not group on shift_id alone.
SELECT shift_instance
FROM v_spc_rule_results_booth01_a_l1
GROUP BY shift_instance
HAVING count(DISTINCT shift_id) <> 1
    OR count(DISTINCT shift_name) <> 1
    ) THEN
        RAISE EXCEPTION 'validate_spc_signal_summary: check 8 failed';
    END IF;
END
$validation$;
