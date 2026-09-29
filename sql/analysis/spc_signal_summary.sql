-- SPC signal and OOS summaries for the initial BOOTH_01 / A-L1 stream.
-- Each statement starts from one row per measurement_id. Signals are rule
-- flags for investigation, not confirmed special causes.

-- Overall performance. Rule counts can overlap; spc_signal is the rule OR.
WITH base AS (
    SELECT
        spc.measurement_id,
        spc.measurement_timestamp,
        spc.booth,
        spc.measurement_point,
        spc.shift_instance,
        spc.shift_id,
        spc.shift_name,
        date_trunc('month', measurement.production_timestamp)::date AS production_month,
        measurement.is_oos,
        spc.rule_1,
        spc.rule_2,
        spc.rule_3,
        spc.rule_4,
        (spc.rule_1 OR spc.rule_2 OR spc.rule_3 OR spc.rule_4) AS any_rule_signal
    FROM v_spc_rule_results_booth01_a_l1 AS spc
    JOIN v_measurement_enriched AS measurement USING (measurement_id)
)
SELECT
    'OVERALL' AS summary_scope,
    booth,
    measurement_point,
    count(DISTINCT measurement_id) AS total_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS signal_rate,
    count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE rule_1)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS rule_1_rate,
    count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE rule_2)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS rule_2_rate,
    count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE rule_3)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS rule_3_rate,
    count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE rule_4)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS rule_4_rate
FROM base
GROUP BY booth, measurement_point
ORDER BY booth, measurement_point;

-- Production-month performance and specification OOS, reported separately.
WITH base AS (
    SELECT
        spc.measurement_id,
        spc.measurement_timestamp,
        spc.booth,
        spc.measurement_point,
        date_trunc('month', measurement.production_timestamp)::date AS production_month,
        measurement.is_oos,
        spc.rule_1,
        spc.rule_2,
        spc.rule_3,
        spc.rule_4,
        (spc.rule_1 OR spc.rule_2 OR spc.rule_3 OR spc.rule_4) AS any_rule_signal
    FROM v_spc_rule_results_booth01_a_l1 AS spc
    JOIN v_measurement_enriched AS measurement USING (measurement_id)
)
SELECT
    production_month,
    booth,
    measurement_point,
    count(DISTINCT measurement_id) AS total_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS signal_rate,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS oos_rate
FROM base
GROUP BY production_month, booth, measurement_point
ORDER BY production_month, booth, measurement_point;

-- Actual shift-instance performance. shift_id/shift_name identify shift type;
-- shift_instance identifies the concrete scheduled shift, including overnights.
WITH base AS (
    SELECT
        spc.measurement_id,
        spc.measurement_timestamp,
        spc.booth,
        spc.measurement_point,
        spc.shift_instance,
        spc.shift_id,
        spc.shift_name,
        measurement.is_oos,
        spc.rule_1,
        spc.rule_2,
        spc.rule_3,
        spc.rule_4,
        (spc.rule_1 OR spc.rule_2 OR spc.rule_3 OR spc.rule_4) AS any_rule_signal
    FROM v_spc_rule_results_booth01_a_l1 AS spc
    JOIN v_measurement_enriched AS measurement USING (measurement_id)
)
SELECT
    shift_instance,
    shift_id,
    shift_name,
    booth,
    measurement_point,
    count(DISTINCT measurement_id) AS total_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal) AS signal_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE any_rule_signal)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS signal_rate,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_measurements,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS oos_rate,
    min(measurement_timestamp) FILTER (WHERE any_rule_signal) AS first_signal_timestamp,
    max(measurement_timestamp) FILTER (WHERE any_rule_signal) AS last_signal_timestamp
FROM base
GROUP BY shift_instance, shift_id, shift_name, booth, measurement_point
ORDER BY shift_instance, shift_id, booth, measurement_point;

-- Long-form rule counts/rates by overall stream, production month, and actual
-- shift instance. Each rule's denominator is all measurements in that scope.
WITH base AS (
    SELECT
        spc.measurement_id,
        spc.booth,
        spc.measurement_point,
        spc.shift_instance,
        spc.shift_id,
        spc.shift_name,
        date_trunc('month', measurement.production_timestamp)::date AS production_month,
        spc.rule_1,
        spc.rule_2,
        spc.rule_3,
        spc.rule_4
    FROM v_spc_rule_results_booth01_a_l1 AS spc
    JOIN v_measurement_enriched AS measurement USING (measurement_id)
), rule_flags AS (
    SELECT
        base.*,
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
), scoped AS (
    SELECT
        CASE
            WHEN grouping(production_month) = 0 THEN 'PRODUCTION_MONTH'
            WHEN grouping(shift_instance) = 0 THEN 'SHIFT_INSTANCE'
            ELSE 'OVERALL'
        END AS summary_scope,
        CASE WHEN grouping(production_month) = 0 THEN production_month ELSE NULL::date END AS production_month,
        CASE WHEN grouping(shift_instance) = 0 THEN shift_instance ELSE NULL::timestamp END AS shift_instance,
        CASE WHEN grouping(shift_id) = 0 THEN shift_id ELSE NULL::integer END AS shift_id,
        CASE WHEN grouping(shift_name) = 0 THEN shift_name ELSE NULL::varchar END AS shift_name,
        rule_name,
        count(DISTINCT measurement_id) AS total_measurements,
        count(DISTINCT measurement_id) FILTER (WHERE is_triggered) AS rule_signal_measurements
    FROM rule_flags
    GROUP BY GROUPING SETS (
        (rule_name),
        (production_month, rule_name),
        (shift_instance, shift_id, shift_name, rule_name)
    )
)
SELECT
    summary_scope,
    production_month,
    shift_instance,
    shift_id,
    shift_name,
    rule_name,
    total_measurements,
    rule_signal_measurements,
    rule_signal_measurements::numeric / nullif(total_measurements, 0) AS rule_signal_rate
FROM scoped
ORDER BY
    CASE summary_scope WHEN 'OVERALL' THEN 1 WHEN 'PRODUCTION_MONTH' THEN 2 ELSE 3 END,
    production_month NULLS FIRST,
    shift_instance NULLS FIRST,
    rule_name;