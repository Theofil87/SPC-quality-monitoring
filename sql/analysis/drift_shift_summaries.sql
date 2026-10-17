-- Reproducible descriptive outputs for the validated BOOTH_01 / A-L1 stream.
-- Execute after sql/views.sql. All rates use the measurement count in their
-- own scope. SPC flags are reused; they are not recalculated or filtered.

-- 1. Production-month summary.
SELECT
    production_month,
    count(DISTINCT measurement_id) AS measurement_count,
    avg(measured_value) AS mean,
    stddev_samp(measured_value) AS sample_std,
    avg(deviation_from_target) AS mean_deviation_from_target,
    count(DISTINCT measurement_id) FILTER (WHERE below_lsl) AS below_lsl_count,
    count(DISTINCT measurement_id) FILTER (WHERE above_usl) AS above_usl_count,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_count,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS oos_rate,
    count(DISTINCT measurement_id) FILTER (WHERE spc_signal) AS spc_signal_count,
    count(DISTINCT measurement_id) FILTER (WHERE spc_signal)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS spc_signal_rate,
    count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_count
FROM v_drift_shift_measurements_booth01_a_l1
GROUP BY production_month
ORDER BY production_month;

-- 2. Concrete scheduled shift instances, including overnight instances.
SELECT
    shift_instance,
    shift_id,
    shift_name,
    min(measurement_timestamp) AS first_measurement_timestamp,
    max(measurement_timestamp) AS last_measurement_timestamp,
    count(DISTINCT measurement_id) AS measurement_count,
    avg(measured_value) AS mean,
    stddev_samp(measured_value) AS sample_std,
    avg(deviation_from_target) AS mean_deviation_from_target,
    coalesce(stddev_samp(measured_value), 0) ^ 2
        * greatest(count(DISTINCT measurement_id) - 1, 0) AS within_sum_of_squares,
    count(DISTINCT measurement_id) FILTER (WHERE below_lsl) AS below_lsl_count,
    count(DISTINCT measurement_id) FILTER (WHERE above_usl) AS above_usl_count,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_count,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS oos_rate,
    count(DISTINCT measurement_id) FILTER (WHERE spc_signal) AS spc_signal_count,
    count(DISTINCT measurement_id) FILTER (WHERE spc_signal)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS spc_signal_rate,
    count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_count
FROM v_drift_shift_measurements_booth01_a_l1
GROUP BY shift_instance, shift_id, shift_name
ORDER BY shift_instance, shift_id;

-- 3. Recurring shift type, pooled across concrete instances.
SELECT
    shift_id,
    shift_name,
    count(DISTINCT shift_instance) AS shift_instance_count,
    count(DISTINCT measurement_id) AS measurement_count,
    avg(measured_value) AS mean,
    stddev_samp(measured_value) AS sample_std,
    avg(deviation_from_target) AS mean_deviation_from_target,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos) AS oos_count,
    count(DISTINCT measurement_id) FILTER (WHERE is_oos)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS oos_rate,
    count(DISTINCT measurement_id) FILTER (WHERE spc_signal) AS spc_signal_count,
    count(DISTINCT measurement_id) FILTER (WHERE spc_signal)::numeric
        / nullif(count(DISTINCT measurement_id), 0) AS spc_signal_rate,
    count(DISTINCT measurement_id) FILTER (WHERE rule_1) AS rule_1_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_2) AS rule_2_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_3) AS rule_3_count,
    count(DISTINCT measurement_id) FILTER (WHERE rule_4) AS rule_4_count
FROM v_drift_shift_measurements_booth01_a_l1
GROUP BY shift_id, shift_name
ORDER BY shift_id;

-- 4. Sufficient statistics for a one-way shift-instance SS decomposition.
SELECT
    shift_instance,
    shift_id,
    shift_name,
    count(DISTINCT measurement_id) AS measurement_count,
    avg(measured_value) AS mean,
    stddev_samp(measured_value) AS sample_std,
    coalesce(stddev_samp(measured_value), 0) ^ 2
        * greatest(count(DISTINCT measurement_id) - 1, 0) AS within_sum_of_squares
FROM v_drift_shift_measurements_booth01_a_l1
GROUP BY shift_instance, shift_id, shift_name
ORDER BY shift_instance, shift_id;
