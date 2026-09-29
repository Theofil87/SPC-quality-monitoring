-- Deterministic aggregation fixtures; flags are inputs, not re-detected here.
DROP TABLE IF EXISTS pg_temp.spc_signal_summary_test_failures;
CREATE TEMP TABLE spc_signal_summary_test_failures AS
WITH fixture AS (
    SELECT
        measurement_id::bigint AS measurement_id,
        booth::text AS booth,
        measurement_point::text AS measurement_point,
        production_timestamp::timestamp AS production_timestamp,
        shift_instance::timestamp AS shift_instance,
        shift_id::integer AS shift_id,
        shift_name::text AS shift_name,
        is_oos::boolean AS is_oos,
        rule_1::boolean AS rule_1,
        rule_2::boolean AS rule_2,
        rule_3::boolean AS rule_3,
        rule_4::boolean AS rule_4,
        reported_spc_signal::boolean AS reported_spc_signal
    FROM (VALUES
        (1001, 'BOOTH_01', 'A-L1', '2026-01-05 06:10:00', '2026-01-05 06:00:00', 1, 'SHIFT_01', false, true,  true,  false, false, true),
        (1002, 'BOOTH_01', 'A-L1', '2026-01-05 06:20:00', '2026-01-05 06:00:00', 1, 'SHIFT_01', true,  false, false, false, false, false),
        (1003, 'BOOTH_01', 'A-L1', '2026-01-05 14:10:00', '2026-01-05 14:00:00', 2, 'SHIFT_02', true,  false, false, true,  false, true),
        (2001, 'BOOTH_01', 'A-L1', '2026-02-05 06:10:00', '2026-02-05 06:00:00', 1, 'SHIFT_01', false, false, false, false, true,  true),
        (2002, 'BOOTH_01', 'A-L1', '2026-02-05 06:20:00', '2026-02-05 06:00:00', 1, 'SHIFT_01', false, false, false, false, false, false),
        (2003, 'BOOTH_01', 'A-L1', '2026-02-05 14:10:00', '2026-02-05 14:00:00', 2, 'SHIFT_02', true,  true,  false, false, true,  true),
        (2004, 'BOOTH_01', 'A-L1', '2026-02-05 14:20:00', '2026-02-05 14:00:00', 2, 'SHIFT_02', false, false, true,  false, false, true)
    ) AS values_table(
        measurement_id, booth, measurement_point, production_timestamp,
        shift_instance, shift_id, shift_name, is_oos,
        rule_1, rule_2, rule_3, rule_4, reported_spc_signal
    )
), base AS (
    SELECT
        fixture.*,
        date_trunc('month', production_timestamp)::date AS production_month,
        (rule_1 OR rule_2 OR rule_3 OR rule_4) AS any_rule_signal
    FROM fixture
), actual_groups AS (
    SELECT
        CASE
            WHEN grouping(production_month) = 0 THEN 'PRODUCTION_MONTH'
            WHEN grouping(shift_instance) = 0 THEN 'SHIFT_INSTANCE'
            ELSE 'OVERALL'
        END AS summary_scope,
        booth,
        measurement_point,
        CASE WHEN grouping(production_month) = 0 THEN production_month ELSE NULL::date END AS production_month,
        CASE WHEN grouping(shift_instance) = 0 THEN shift_instance ELSE NULL::timestamp END AS shift_instance,
        CASE WHEN grouping(shift_id) = 0 THEN shift_id ELSE NULL::integer END AS shift_id,
        CASE WHEN grouping(shift_name) = 0 THEN shift_name ELSE NULL::text END AS shift_name,
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal)::numeric
            / nullif(count(DISTINCT measurement_id), 0) AS signal_rate,
        count(DISTINCT measurement_id) FILTER (WHERE is_oos)::numeric
            / nullif(count(DISTINCT measurement_id), 0) AS oos_rate,
        count(DISTINCT measurement_id) FILTER (WHERE rule_1)::numeric
            / nullif(count(DISTINCT measurement_id), 0) AS rule_1_rate,
        count(DISTINCT measurement_id) FILTER (WHERE rule_2)::numeric
            / nullif(count(DISTINCT measurement_id), 0) AS rule_2_rate,
        count(DISTINCT measurement_id) FILTER (WHERE rule_3)::numeric
            / nullif(count(DISTINCT measurement_id), 0) AS rule_3_rate,
        count(DISTINCT measurement_id) FILTER (WHERE rule_4)::numeric
            / nullif(count(DISTINCT measurement_id), 0) AS rule_4_rate
    FROM base
    GROUP BY GROUPING SETS (
        (booth, measurement_point),
        (booth, measurement_point, production_month),
        (booth, measurement_point, shift_instance, shift_id, shift_name)
    )
), expected_groups AS (
    SELECT *
    FROM (VALUES
        ('OVERALL', 'BOOTH_01', 'A-L1', NULL::date, NULL::timestamp, NULL::integer, NULL::text, 7, 5, 3, 2, 2, 1, 2),
        ('PRODUCTION_MONTH', 'BOOTH_01', 'A-L1', DATE '2026-01-01', NULL::timestamp, NULL::integer, NULL::text, 3, 2, 2, 1, 1, 1, 0),
        ('PRODUCTION_MONTH', 'BOOTH_01', 'A-L1', DATE '2026-02-01', NULL::timestamp, NULL::integer, NULL::text, 4, 3, 1, 1, 1, 0, 2),
        ('SHIFT_INSTANCE', 'BOOTH_01', 'A-L1', NULL::date, TIMESTAMP '2026-01-05 06:00:00', 1, 'SHIFT_01', 2, 1, 1, 1, 1, 0, 0),
        ('SHIFT_INSTANCE', 'BOOTH_01', 'A-L1', NULL::date, TIMESTAMP '2026-01-05 14:00:00', 2, 'SHIFT_02', 1, 1, 1, 0, 0, 1, 0),
        ('SHIFT_INSTANCE', 'BOOTH_01', 'A-L1', NULL::date, TIMESTAMP '2026-02-05 06:00:00', 1, 'SHIFT_01', 2, 1, 0, 0, 0, 0, 1),
        ('SHIFT_INSTANCE', 'BOOTH_01', 'A-L1', NULL::date, TIMESTAMP '2026-02-05 14:00:00', 2, 'SHIFT_02', 2, 2, 1, 1, 1, 0, 1)
    ) AS values_table(
        summary_scope, booth, measurement_point, production_month,
        shift_instance, shift_id, shift_name, total_measurements,
        signal_measurements, oos_measurements, rule_1_measurements,
        rule_2_measurements, rule_3_measurements, rule_4_measurements
    )
), group_failures AS (
    SELECT
        'GROUP_COUNTS_OR_RATES'::text AS check_name,
        concat_ws('|', expected.summary_scope, expected.production_month, expected.shift_instance) AS check_key
    FROM expected_groups AS expected
    LEFT JOIN actual_groups AS actual
        ON actual.summary_scope = expected.summary_scope
       AND actual.booth = expected.booth
       AND actual.measurement_point = expected.measurement_point
       AND actual.production_month IS NOT DISTINCT FROM expected.production_month
       AND actual.shift_instance IS NOT DISTINCT FROM expected.shift_instance
       AND actual.shift_id IS NOT DISTINCT FROM expected.shift_id
       AND actual.shift_name IS NOT DISTINCT FROM expected.shift_name
    WHERE actual.summary_scope IS NULL
       OR actual.total_measurements <> expected.total_measurements
       OR actual.signal_measurements <> expected.signal_measurements
       OR actual.oos_measurements <> expected.oos_measurements
       OR actual.rule_1_measurements <> expected.rule_1_measurements
       OR actual.rule_2_measurements <> expected.rule_2_measurements
       OR actual.rule_3_measurements <> expected.rule_3_measurements
       OR actual.rule_4_measurements <> expected.rule_4_measurements
       OR actual.signal_rate IS DISTINCT FROM expected.signal_measurements::numeric / expected.total_measurements
       OR actual.oos_rate IS DISTINCT FROM expected.oos_measurements::numeric / expected.total_measurements
       OR actual.rule_1_rate IS DISTINCT FROM expected.rule_1_measurements::numeric / expected.total_measurements
       OR actual.rule_2_rate IS DISTINCT FROM expected.rule_2_measurements::numeric / expected.total_measurements
       OR actual.rule_3_rate IS DISTINCT FROM expected.rule_3_measurements::numeric / expected.total_measurements
       OR actual.rule_4_rate IS DISTINCT FROM expected.rule_4_measurements::numeric / expected.total_measurements
), rule_flags AS (
    SELECT
        base.measurement_id,
        base.production_month,
        base.shift_instance,
        base.shift_id,
        base.shift_name,
        rule_flag.rule_name,
        rule_flag.is_triggered
    FROM base
    CROSS JOIN LATERAL (
        VALUES
            ('RULE_1', base.rule_1),
            ('RULE_2', base.rule_2),
            ('RULE_3', base.rule_3),
            ('RULE_4', base.rule_4)
    ) AS rule_flag(rule_name, is_triggered)
), actual_rule_groups AS (
    SELECT
        CASE
            WHEN grouping(production_month) = 0 THEN 'PRODUCTION_MONTH'
            WHEN grouping(shift_instance) = 0 THEN 'SHIFT_INSTANCE'
            ELSE 'OVERALL'
        END AS summary_scope,
        CASE WHEN grouping(production_month) = 0 THEN production_month ELSE NULL::date END AS production_month,
        CASE WHEN grouping(shift_instance) = 0 THEN shift_instance ELSE NULL::timestamp END AS shift_instance,
        CASE WHEN grouping(shift_id) = 0 THEN shift_id ELSE NULL::integer END AS shift_id,
        CASE WHEN grouping(shift_name) = 0 THEN shift_name ELSE NULL::text END AS shift_name,
        rule_name,
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE is_triggered) AS rule_signal_measurements
    FROM rule_flags
    GROUP BY GROUPING SETS (
        (rule_name),
        (production_month, rule_name),
        (shift_instance, shift_id, shift_name, rule_name)
    )
), expected_rule_groups AS (
    SELECT
        actual.summary_scope,
        actual.production_month,
        actual.shift_instance,
        actual.shift_id,
        actual.shift_name,
        expected.rule_name,
        actual.total_measurements,
        expected.rule_signal_measurements
    FROM actual_groups AS actual
    CROSS JOIN LATERAL (
        VALUES
            ('RULE_1', actual.rule_1_measurements),
            ('RULE_2', actual.rule_2_measurements),
            ('RULE_3', actual.rule_3_measurements),
            ('RULE_4', actual.rule_4_measurements)
    ) AS expected(rule_name, rule_signal_measurements)
), rule_group_failures AS (
    SELECT
        'RULE_LONG_FORM'::text AS check_name,
        concat_ws('|', expected.summary_scope, expected.rule_name, expected.production_month, expected.shift_instance) AS check_key
    FROM expected_rule_groups AS expected
    LEFT JOIN actual_rule_groups AS actual
        ON actual.summary_scope = expected.summary_scope
       AND actual.rule_name = expected.rule_name
       AND actual.production_month IS NOT DISTINCT FROM expected.production_month
       AND actual.shift_instance IS NOT DISTINCT FROM expected.shift_instance
       AND actual.shift_id IS NOT DISTINCT FROM expected.shift_id
       AND actual.shift_name IS NOT DISTINCT FROM expected.shift_name
    WHERE actual.summary_scope IS NULL
       OR actual.total_measurements <> expected.total_measurements
       OR actual.rule_signal_measurements <> expected.rule_signal_measurements
       OR actual.rule_signal_measurements::numeric / nullif(actual.total_measurements, 0)
            IS DISTINCT FROM expected.rule_signal_measurements::numeric / expected.total_measurements
), signal_failures AS (
    SELECT
        'SPC_SIGNAL_NOT_RULE_OR'::text AS check_name,
        measurement_id::text AS check_key
    FROM base
    WHERE reported_spc_signal IS DISTINCT FROM any_rule_signal
    UNION ALL
    SELECT
        'MEASUREMENT_ID_NOT_UNIQUE'::text,
        measurement_id::text
    FROM base
    GROUP BY measurement_id
    HAVING count(*) <> 1
), independence AS (
    SELECT
        count(*) FILTER (WHERE any_rule_signal AND is_oos) AS signal_and_oos,
        count(*) FILTER (WHERE any_rule_signal AND NOT is_oos) AS signal_only,
        count(*) FILTER (WHERE NOT any_rule_signal AND is_oos) AS oos_only,
        count(*) FILTER (WHERE NOT any_rule_signal AND NOT is_oos) AS neither
    FROM base
), independence_failures AS (
    SELECT
        'OOS_SIGNAL_INDEPENDENCE'::text AS check_name,
        concat_ws('|', signal_and_oos, signal_only, oos_only, neither) AS check_key
    FROM independence
    WHERE signal_and_oos <> 2
       OR signal_only <> 3
       OR oos_only <> 1
       OR neither <> 1
), failures AS (
    SELECT * FROM group_failures
    UNION ALL SELECT * FROM rule_group_failures
    UNION ALL SELECT * FROM signal_failures
    UNION ALL SELECT * FROM independence_failures
)
SELECT * FROM failures;

DO $$
DECLARE
    failed_check_count BIGINT;
BEGIN
    SELECT count(*) INTO failed_check_count
    FROM pg_temp.spc_signal_summary_test_failures;

    IF failed_check_count > 0 THEN
        RAISE EXCEPTION 'SPC signal summary regression checks failed: %', failed_check_count;
    END IF;
END
$$;

SELECT 'PASS' AS validation_status, 0 AS failed_check_count;
DROP TABLE pg_temp.spc_signal_summary_test_failures;