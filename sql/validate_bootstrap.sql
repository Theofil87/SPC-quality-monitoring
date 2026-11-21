-- Canonical end-to-end validation for the database bootstrap.
-- All checks fail transactionally with ON_ERROR_STOP.
\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
    expected_count BIGINT;
    actual_count BIGINT;
    invalid_count BIGINT;
BEGIN
    SELECT count(*) INTO expected_count
    FROM fact_quality_measurement;

    SELECT count(*) INTO actual_count
    FROM v_measurement_enriched;

    IF expected_count = 0 OR actual_count <> expected_count THEN
        RAISE EXCEPTION
            'Measurement enrichment mismatch: fact %, enriched %',
            expected_count, actual_count;
    END IF;

    SELECT count(*) INTO actual_count
    FROM spc_baseline
    WHERE status = 'ACTIVE';
    IF actual_count <> 1 THEN
        RAISE EXCEPTION 'Expected exactly one ACTIVE baseline, found %', actual_count;
    END IF;

    SELECT count(*) INTO expected_count
    FROM v_measurement_enriched AS measurement
    JOIN spc_baseline AS baseline
      ON baseline.booth_id = measurement.booth_id
     AND baseline.measurement_point_id = measurement.measurement_point_id
     AND baseline.specification_id = measurement.specification_id
     AND baseline.status = 'ACTIVE';

    SELECT count(*) INTO actual_count
    FROM v_spc_rule_results_booth01_a_l1;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION
            'SPC grain mismatch: eligible %, result %',
            expected_count, actual_count;
    END IF;

    SELECT count(*) INTO invalid_count
    FROM v_spc_rule_results
    WHERE (baseline_id IS NOT NULL
           AND spc_signal IS DISTINCT FROM (rule_1 OR rule_2 OR rule_3 OR rule_4))
       OR (
            baseline_id IS NULL
            AND (rule_1 OR rule_2 OR rule_3 OR rule_4 OR spc_signal IS NOT NULL)
       )
       OR spc_evaluation_status IS DISTINCT FROM
            CASE WHEN baseline_id IS NULL THEN 'NOT_EVALUATED' ELSE 'EVALUATED' END;
    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'Invalid SPC flags detected: % rows', invalid_count;
    END IF;

    SELECT count(*) INTO invalid_count
    FROM v_spc_rule_results AS result
    JOIN spc_baseline AS baseline USING (baseline_id)
    WHERE result.center_line IS DISTINCT FROM baseline.center_line
       OR result.sigma IS DISTINCT FROM baseline.sigma
       OR result.i_lcl IS DISTINCT FROM baseline.i_lcl
       OR result.i_ucl IS DISTINCT FROM baseline.i_ucl
       OR result.mr_center IS DISTINCT FROM baseline.mr_center
       OR result.mr_ucl IS DISTINCT FROM baseline.mr_ucl;
    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'Stored baseline limits were not preserved: % rows', invalid_count;
    END IF;

    SELECT count(*) INTO invalid_count
    FROM (
        SELECT measurement_id
        FROM v_spc_rule_results
        WHERE booth = 'BOOTH_01'
          AND measurement_point = 'A-L1'
        GROUP BY measurement_id
        HAVING count(*) <> 1
    ) AS duplicate_results;
    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'SPC result IDs are duplicated: % rows', invalid_count;
    END IF;
END
$$;

COMMIT;

SELECT
    'PASS' AS validation_status,
    (SELECT count(*) FROM fact_quality_measurement) AS measurement_count,
    (SELECT count(*) FROM v_spc_rule_results_booth01_a_l1) AS spc_result_count,
    (
        SELECT count(*)
        FROM v_spc_rule_results
        WHERE baseline_id IS NOT NULL
          AND booth = 'BOOTH_01'
          AND measurement_point = 'A-L1'
    ) AS baseline_covered_count,
    (
        SELECT count(*)
        FROM v_spc_rule_results
        WHERE spc_signal
          AND booth = 'BOOTH_01'
          AND measurement_point = 'A-L1'
    ) AS spc_signal_count;
