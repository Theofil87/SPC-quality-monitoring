-- Deterministic SQL regression fixtures for the SPC rule semantics.
-- The synthetic fixtures use CL = 0 and sigma = 1 so zone boundaries are exact.
DROP TABLE IF EXISTS pg_temp.spc_rule_test_failures;
CREATE TEMP TABLE spc_rule_test_failures AS
WITH fixture AS (
    SELECT
        test_case,
        shift_instance,
        timestamp_offset,
        measurement_id::bigint AS measurement_id,
        measured_value::numeric AS measured_value
    FROM (VALUES
        ('rule_1_boundary', 1, 1, 101, 3.000),
        ('rule_1_boundary', 1, 2, 102, 3.001),
        ('rule_1_lower_boundary', 1, 1, 111, -3.000),
        ('rule_1_lower_boundary', 1, 2, 112, -3.001),

        ('rule_2_same_side', 1, 1, 201, 2.100),
        ('rule_2_same_side', 1, 2, 202, 2.200),
        ('rule_2_same_side', 1, 3, 203, 0.000),
        ('rule_2_mixed_sides', 1, 1, 211, 2.100),
        ('rule_2_mixed_sides', 1, 2, 212, -2.100),
        ('rule_2_mixed_sides', 1, 3, 213, 0.000),
        ('rule_2_boundary', 1, 1, 221, 2.000),
        ('rule_2_boundary', 1, 2, 222, 2.200),
        ('rule_2_boundary', 1, 3, 223, 0.000),

        ('rule_3_same_side', 1, 1, 301, 2.100),
        ('rule_3_same_side', 1, 2, 302, 1.100),
        ('rule_3_same_side', 1, 3, 303, 1.200),
        ('rule_3_same_side', 1, 4, 304, 0.000),
        ('rule_3_same_side', 1, 5, 305, 1.500),
        ('rule_3_mixed_sides', 1, 1, 311, 1.100),
        ('rule_3_mixed_sides', 1, 2, 312, -1.100),
        ('rule_3_mixed_sides', 1, 3, 313, 1.200),
        ('rule_3_mixed_sides', 1, 4, 314, -1.200),
        ('rule_3_mixed_sides', 1, 5, 315, 0.000),
        ('rule_3_boundary', 1, 1, 321, 1.000),
        ('rule_3_boundary', 1, 2, 322, 1.100),
        ('rule_3_boundary', 1, 3, 323, 1.100),
        ('rule_3_boundary', 1, 4, 324, 1.100),
        ('rule_3_boundary', 1, 5, 325, 0.000),

        ('rule_4_threshold', 1, 1, 401, 0.500),
        ('rule_4_threshold', 1, 2, 402, 0.500),
        ('rule_4_threshold', 1, 3, 403, 0.500),
        ('rule_4_threshold', 1, 4, 404, 0.500),
        ('rule_4_threshold', 1, 5, 405, 0.500),
        ('rule_4_threshold', 1, 6, 406, 0.500),
        ('rule_4_threshold', 1, 7, 407, 0.500),
        ('rule_4_threshold', 1, 8, 408, 0.500),
        ('rule_4_threshold', 1, 9, 409, 0.500),
        ('rule_4_center_reset', 1, 1, 411, 0.500),
        ('rule_4_center_reset', 1, 2, 412, 0.500),
        ('rule_4_center_reset', 1, 3, 413, 0.500),
        ('rule_4_center_reset', 1, 4, 414, 0.500),
        ('rule_4_center_reset', 1, 5, 415, 0.500),
        ('rule_4_center_reset', 1, 6, 416, 0.500),
        ('rule_4_center_reset', 1, 7, 417, 0.500),
        ('rule_4_center_reset', 1, 8, 418, 0.000),
        ('rule_4_center_reset', 1, 9, 419, 0.500),

        ('shift_rule_2_reset', 1, 1, 501, 2.500),
        ('shift_rule_2_reset', 1, 2, 502, 2.500),
        ('shift_rule_2_reset', 2, 1, 503, 0.000),
        ('shift_rule_3_reset', 1, 1, 511, 1.500),
        ('shift_rule_3_reset', 1, 2, 512, 1.500),
        ('shift_rule_3_reset', 1, 3, 513, 1.500),
        ('shift_rule_3_reset', 1, 4, 514, 1.500),
        ('shift_rule_3_reset', 2, 1, 515, 1.500),
        ('shift_rule_4_reset', 1, 1, 521, 0.500),
        ('shift_rule_4_reset', 1, 2, 522, 0.500),
        ('shift_rule_4_reset', 1, 3, 523, 0.500),
        ('shift_rule_4_reset', 1, 4, 524, 0.500),
        ('shift_rule_4_reset', 1, 5, 525, 0.500),
        ('shift_rule_4_reset', 1, 6, 526, 0.500),
        ('shift_rule_4_reset', 1, 7, 527, 0.500),
        ('shift_rule_4_reset', 2, 1, 528, 0.500),

        ('mr_shift_reset', 1, 1, 601, 0.000),
        ('mr_shift_reset', 1, 2, 602, 0.100),
        ('mr_shift_reset', 2, 1, 603, 2.000),
        ('mr_shift_reset', 2, 2, 604, 2.100),

        ('deterministic_tie_order', 1, -1, 700, 2.500),
        ('deterministic_tie_order', 1, 0, 702, 2.500),
        ('deterministic_tie_order', 1, 0, 701, 0.000),
        ('deterministic_tie_order', 1, 1, 703, 2.500)
    ) AS values_table(test_case, shift_instance, timestamp_offset, measurement_id, measured_value)
), ordered AS (
    SELECT
        fixture.*,
        row_number() OVER instance_order AS observation_number,
        lag(measured_value) OVER instance_order AS previous_value
    FROM fixture
    WINDOW instance_order AS (
        PARTITION BY test_case, shift_instance
        ORDER BY timestamp_offset, measurement_id
    )
), ranges AS (
    SELECT
        ordered.*,
        CASE WHEN previous_value IS NULL THEN NULL
             ELSE abs(measured_value - previous_value)
        END AS moving_range,
        CASE WHEN measured_value > 3 THEN 1 ELSE 0 END AS beyond_plus_3,
        CASE WHEN measured_value < -3 THEN 1 ELSE 0 END AS beyond_minus_3,
        CASE WHEN measured_value > 2 THEN 1 ELSE 0 END AS beyond_plus_2,
        CASE WHEN measured_value < -2 THEN 1 ELSE 0 END AS beyond_minus_2,
        CASE WHEN measured_value > 1 THEN 1 ELSE 0 END AS beyond_plus_1,
        CASE WHEN measured_value < -1 THEN 1 ELSE 0 END AS beyond_minus_1,
        CASE WHEN measured_value > 0 THEN 1 WHEN measured_value < 0 THEN -1 ELSE 0 END AS center_line_side
    FROM ordered
), windows AS (
    SELECT
        ranges.*,
        sum(beyond_plus_2) OVER three_rows AS plus_2_count_3,
        sum(beyond_minus_2) OVER three_rows AS minus_2_count_3,
        sum(beyond_plus_1) OVER five_rows AS plus_1_count_5,
        sum(beyond_minus_1) OVER five_rows AS minus_1_count_5,
        lag(center_line_side, 1, 0) OVER instance_order AS previous_center_line_side
    FROM ranges
    WINDOW
        instance_order AS (
            PARTITION BY test_case, shift_instance
            ORDER BY timestamp_offset, measurement_id
        ),
        three_rows AS (
            PARTITION BY test_case, shift_instance
            ORDER BY timestamp_offset, measurement_id
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ),
        five_rows AS (
            PARTITION BY test_case, shift_instance
            ORDER BY timestamp_offset, measurement_id
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        )
), run_groups AS (
    SELECT
        windows.*,
        sum(CASE WHEN center_line_side <> previous_center_line_side THEN 1 ELSE 0 END)
            OVER (
                PARTITION BY test_case, shift_instance
                ORDER BY timestamp_offset, measurement_id
            ) AS run_id
    FROM windows
), scored AS (
    SELECT
        run_groups.*,
        count(*) OVER (
            PARTITION BY test_case, shift_instance, run_id
            ORDER BY timestamp_offset, measurement_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS run_length,
        (beyond_plus_3 = 1 OR beyond_minus_3 = 1) AS rule_1,
        (observation_number >= 3 AND (plus_2_count_3 >= 2 OR minus_2_count_3 >= 2)) AS rule_2,
        (observation_number >= 5 AND (plus_1_count_5 >= 4 OR minus_1_count_5 >= 4)) AS rule_3
    FROM run_groups
), results AS (
    SELECT
        scored.*,
        (center_line_side <> 0 AND run_length >= 8) AS rule_4
    FROM scored
), actual AS (
    SELECT
        test_case,
        shift_instance,
        array_agg(measurement_id ORDER BY timestamp_offset, measurement_id) AS ordered_ids,
        array_agg(moving_range ORDER BY timestamp_offset, measurement_id) AS moving_ranges,
        array_agg(measurement_id ORDER BY timestamp_offset, measurement_id) FILTER (WHERE rule_1) AS rule_1_ids,
        array_agg(measurement_id ORDER BY timestamp_offset, measurement_id) FILTER (WHERE rule_2) AS rule_2_ids,
        array_agg(measurement_id ORDER BY timestamp_offset, measurement_id) FILTER (WHERE rule_3) AS rule_3_ids,
        array_agg(measurement_id ORDER BY timestamp_offset, measurement_id) FILTER (WHERE rule_4) AS rule_4_ids,
        count(*) FILTER (WHERE observation_number = 1 AND moving_range IS NULL) AS first_mr_null_count,
        count(*) FILTER (WHERE observation_number > 1 AND moving_range IS NULL) AS later_mr_null_count
    FROM results
    GROUP BY test_case, shift_instance
), expected AS (
    SELECT *
    FROM (VALUES
        ('rule_1_boundary', 1, ARRAY[101,102]::bigint[], ARRAY[NULL::numeric,0.001], ARRAY[102]::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('rule_1_lower_boundary', 1, ARRAY[111,112]::bigint[], ARRAY[NULL::numeric,0.001], ARRAY[112]::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('rule_2_same_side', 1, ARRAY[201,202,203]::bigint[], ARRAY[NULL::numeric,0.1,2.2], NULL::bigint[], ARRAY[203]::bigint[], NULL::bigint[], NULL::bigint[]),
        ('rule_2_mixed_sides', 1, ARRAY[211,212,213]::bigint[], ARRAY[NULL::numeric,4.2,2.1], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('rule_2_boundary', 1, ARRAY[221,222,223]::bigint[], ARRAY[NULL::numeric,0.2,2.2], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('rule_3_same_side', 1, ARRAY[301,302,303,304,305]::bigint[], ARRAY[NULL::numeric,1.0,0.1,1.2,1.5], NULL::bigint[], NULL::bigint[], ARRAY[305]::bigint[], NULL::bigint[]),
        ('rule_3_mixed_sides', 1, ARRAY[311,312,313,314,315]::bigint[], ARRAY[NULL::numeric,2.2,2.3,2.4,1.2], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('rule_3_boundary', 1, ARRAY[321,322,323,324,325]::bigint[], ARRAY[NULL::numeric,0.1,0.0,0.0,1.1], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('rule_4_threshold', 1, ARRAY[401,402,403,404,405,406,407,408,409]::bigint[], ARRAY[NULL::numeric,0,0,0,0,0,0,0,0], NULL::bigint[], NULL::bigint[], NULL::bigint[], ARRAY[408,409]::bigint[]),
        ('rule_4_center_reset', 1, ARRAY[411,412,413,414,415,416,417,418,419]::bigint[], ARRAY[NULL::numeric,0,0,0,0,0,0,0.5,0.5], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('shift_rule_2_reset', 1, ARRAY[501,502]::bigint[], ARRAY[NULL::numeric,0], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('shift_rule_2_reset', 2, ARRAY[503]::bigint[], ARRAY[NULL::numeric], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('shift_rule_3_reset', 1, ARRAY[511,512,513,514]::bigint[], ARRAY[NULL::numeric,0,0,0], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('shift_rule_3_reset', 2, ARRAY[515]::bigint[], ARRAY[NULL::numeric], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('shift_rule_4_reset', 1, ARRAY[521,522,523,524,525,526,527]::bigint[], ARRAY[NULL::numeric,0,0,0,0,0,0], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('shift_rule_4_reset', 2, ARRAY[528]::bigint[], ARRAY[NULL::numeric], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('mr_shift_reset', 1, ARRAY[601,602]::bigint[], ARRAY[NULL::numeric,0.1], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('mr_shift_reset', 2, ARRAY[603,604]::bigint[], ARRAY[NULL::numeric,0.1], NULL::bigint[], NULL::bigint[], NULL::bigint[], NULL::bigint[]),
        ('deterministic_tie_order', 1, ARRAY[700,701,702,703]::bigint[], ARRAY[NULL::numeric,2.5,2.5,0], NULL::bigint[], ARRAY[702,703]::bigint[], NULL::bigint[], NULL::bigint[])
    ) AS values_table(test_case, shift_instance, expected_ordered_ids, expected_moving_ranges, expected_rule_1_ids, expected_rule_2_ids, expected_rule_3_ids, expected_rule_4_ids)
), failures AS (
    SELECT
        expected.test_case,
        expected.shift_instance,
        expected.expected_ordered_ids,
        expected.expected_moving_ranges,
        expected.expected_rule_1_ids,
        expected.expected_rule_2_ids,
        expected.expected_rule_3_ids,
        expected.expected_rule_4_ids,
        actual.ordered_ids,
        actual.moving_ranges,
        actual.rule_1_ids,
        actual.rule_2_ids,
        actual.rule_3_ids,
        actual.rule_4_ids,
        actual.first_mr_null_count,
        actual.later_mr_null_count
    FROM expected
    LEFT JOIN actual USING (test_case, shift_instance)
    WHERE actual.test_case IS NULL
       OR actual.ordered_ids IS DISTINCT FROM expected.expected_ordered_ids
       OR actual.moving_ranges IS DISTINCT FROM expected.expected_moving_ranges
       OR coalesce(actual.rule_1_ids, ARRAY[]::bigint[]) IS DISTINCT FROM coalesce(expected.expected_rule_1_ids, ARRAY[]::bigint[])
       OR coalesce(actual.rule_2_ids, ARRAY[]::bigint[]) IS DISTINCT FROM coalesce(expected.expected_rule_2_ids, ARRAY[]::bigint[])
       OR coalesce(actual.rule_3_ids, ARRAY[]::bigint[]) IS DISTINCT FROM coalesce(expected.expected_rule_3_ids, ARRAY[]::bigint[])
       OR coalesce(actual.rule_4_ids, ARRAY[]::bigint[]) IS DISTINCT FROM coalesce(expected.expected_rule_4_ids, ARRAY[]::bigint[])
       OR actual.first_mr_null_count <> 1
       OR actual.later_mr_null_count <> 0
)
SELECT * FROM failures;

DO $$
DECLARE
    failed_fixture_count BIGINT;
BEGIN
    SELECT count(*) INTO failed_fixture_count
    FROM pg_temp.spc_rule_test_failures;

    IF failed_fixture_count > 0 THEN
        RAISE EXCEPTION 'SPC regression fixtures failed: %', failed_fixture_count;
    END IF;
END
$$;

SELECT 'PASS' AS validation_status, 0 AS failed_fixture_count;
DROP TABLE pg_temp.spc_rule_test_failures;