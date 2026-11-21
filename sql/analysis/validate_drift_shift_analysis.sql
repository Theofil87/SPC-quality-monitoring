-- Run with psql; a failed check raises an error and exits nonzero.
-- Seeded measurement totals are fixed; signal totals depend on the assigned baselines.
\set ON_ERROR_STOP on

DO $$
DECLARE
    totals record;
BEGIN
    SELECT count(*) AS measurement_count,
           count(DISTINCT measurement_id) AS unique_count,
           count(DISTINCT shift_instance) AS shift_count,
           count(*) FILTER (WHERE is_oos) AS oos_count
    INTO totals
    FROM v_drift_shift_measurements_booth01_a_l1;

    IF totals.measurement_count <> 4650 OR totals.unique_count <> 4650
       OR totals.shift_count <> 465 OR totals.oos_count <> 56 THEN
        RAISE EXCEPTION 'Drift input totals invalid: %', totals;
    END IF;

    IF EXISTS (
        WITH drift AS MATERIALIZED (
            SELECT * FROM v_drift_shift_measurements_booth01_a_l1
        ), source AS MATERIALIZED (
            SELECT * FROM v_capability_measurements_booth01_a_l1
        )
        SELECT 1 FROM drift d
        FULL JOIN source s USING (measurement_id)
        WHERE d.measurement_id IS NULL OR s.measurement_id IS NULL
           OR d.baseline_id IS DISTINCT FROM s.baseline_id
           OR d.spc_evaluation_status IS DISTINCT FROM s.spc_evaluation_status
           OR d.spc_signal IS DISTINCT FROM s.spc_signal
           OR d.spc_evaluation_status IS DISTINCT FROM
                CASE WHEN d.baseline_id IS NULL THEN 'NOT_EVALUATED' ELSE 'EVALUATED' END
           OR (d.baseline_id IS NULL AND d.spc_signal IS NOT NULL)
           OR (d.baseline_id IS NOT NULL AND d.spc_signal IS NULL)
    ) THEN
        RAISE EXCEPTION 'Drift SPC coverage or signal does not reconcile with source';
    END IF;

    IF EXISTS (
        SELECT 1 FROM v_drift_shift_measurements_booth01_a_l1
        GROUP BY shift_instance
        HAVING count(DISTINCT shift_id) <> 1
            OR count(DISTINCT shift_name) <> 1
            OR count(DISTINCT measurement_id) <> 10
    ) THEN
        RAISE EXCEPTION 'Invalid actual shift mapping or measurement count';
    END IF;

    IF EXISTS (
        SELECT 1 FROM v_drift_shift_measurements_booth01_a_l1
        WHERE shift_name = 'SHIFT_03'
          AND (shift_instance::time <> time '22:00'
               OR measurement_timestamp < shift_instance
               OR measurement_timestamp >= shift_instance + interval '8 hours')
    ) THEN
        RAISE EXCEPTION 'Invalid overnight shift assignment';
    END IF;

    IF EXISTS (
        WITH base AS (
            SELECT * FROM v_drift_shift_measurements_booth01_a_l1
        ), overall AS (
            SELECT count(*) AS n, count(*) FILTER (WHERE is_oos) AS oos,
                   count(*) FILTER (WHERE spc_signal IS NOT NULL) AS evaluated,
                   count(*) FILTER (WHERE spc_signal) AS signals FROM base
        ), grouped AS (
            SELECT grouping(production_month, shift_instance, shift_id) AS scope,
                   count(*) AS n, count(*) FILTER (WHERE is_oos) AS oos,
                   count(*) FILTER (WHERE spc_signal IS NOT NULL) AS evaluated,
                   count(*) FILTER (WHERE spc_signal) AS signals
            FROM base
            GROUP BY GROUPING SETS ((production_month), (shift_instance), (shift_id))
        ), summed AS (
            SELECT scope, sum(n) AS n, sum(oos) AS oos,
                   sum(evaluated) AS evaluated, sum(signals) AS signals
            FROM grouped GROUP BY scope
        )
        SELECT 1 FROM summed CROSS JOIN overall
        WHERE summed.n <> overall.n OR summed.oos <> overall.oos
           OR summed.evaluated <> overall.evaluated OR summed.signals <> overall.signals
    ) THEN
        RAISE EXCEPTION 'Drift grouped totals do not reconcile';
    END IF;

    IF EXISTS (
        WITH base AS (
            SELECT measured_value, shift_instance FROM v_drift_shift_measurements_booth01_a_l1
        ), overall AS (
            SELECT avg(measured_value) AS mean FROM base
        ), groups AS (
            SELECT shift_instance, count(*) AS n, avg(measured_value) AS mean,
                   coalesce(stddev_samp(measured_value), 0) ^ 2
                     * greatest(count(*) - 1, 0) AS within_ss
            FROM base GROUP BY shift_instance
        ), sums AS (
            SELECT (SELECT sum((measured_value - mean) ^ 2) FROM base CROSS JOIN overall) AS total_ss,
                   sum(within_ss) AS within_ss,
                   sum(n * (mean - (SELECT mean FROM overall)) ^ 2) AS between_ss
            FROM groups
        )
        SELECT 1 FROM sums WHERE abs(total_ss - within_ss - between_ss) > 0.000001
    ) THEN
        RAISE EXCEPTION 'Shift variance decomposition does not reconcile';
    END IF;
END
$$;
