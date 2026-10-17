-- Every statement returns zero rows when the drift/shift analysis contract is valid.

-- 1. Canonical measurement grain and expected validated-stream totals.
WITH totals AS (
    SELECT
        count(*) AS measurement_count,
        count(DISTINCT measurement_id) AS unique_measurement_count,
        count(DISTINCT shift_instance) AS shift_instance_count,
        count(*) FILTER (WHERE is_oos) AS oos_count,
        count(*) FILTER (WHERE spc_signal) AS spc_signal_count
    FROM v_drift_shift_measurements_booth01_a_l1
)
SELECT *
FROM totals
WHERE measurement_count <> 4650
   OR unique_measurement_count <> 4650
   OR shift_instance_count <> 465
   OR oos_count <> 56
   OR spc_signal_count <> 174;

-- 2. Each concrete shift maps to exactly one type and contains 10 readings.
SELECT shift_instance
FROM v_drift_shift_measurements_booth01_a_l1
GROUP BY shift_instance
HAVING count(DISTINCT shift_id) <> 1
    OR count(DISTINCT shift_name) <> 1
    OR count(DISTINCT measurement_id) <> 10;

-- 3. Overnight records retain the scheduled 22:00 start and remain inside it.
SELECT measurement_id, shift_instance, measurement_timestamp
FROM v_drift_shift_measurements_booth01_a_l1
WHERE shift_name = 'SHIFT_03'
  AND (
      shift_instance::time <> time '22:00'
      OR measurement_timestamp < shift_instance
      OR measurement_timestamp >= shift_instance + interval '8 hours'
  );

-- 4. Every grouped scope reconciles measurement, OOS, and signal totals.
WITH base AS (
    SELECT * FROM v_drift_shift_measurements_booth01_a_l1
), overall AS (
    SELECT count(*) AS measurement_count, count(*) FILTER (WHERE is_oos) AS oos_count,
           count(*) FILTER (WHERE spc_signal) AS signal_count FROM base
), monthly AS (
    SELECT production_month, count(*) AS measurement_count,
           count(*) FILTER (WHERE is_oos) AS oos_count,
           count(*) FILTER (WHERE spc_signal) AS signal_count
    FROM base GROUP BY production_month
), instances AS (
    SELECT shift_instance, count(*) AS measurement_count,
           count(*) FILTER (WHERE is_oos) AS oos_count,
           count(*) FILTER (WHERE spc_signal) AS signal_count
    FROM base GROUP BY shift_instance
), types AS (
    SELECT shift_id, count(*) AS measurement_count,
           count(*) FILTER (WHERE is_oos) AS oos_count,
           count(*) FILTER (WHERE spc_signal) AS signal_count
    FROM base GROUP BY shift_id
), grouped AS (
    SELECT 'monthly' AS scope, sum(measurement_count) AS measurement_count,
           sum(oos_count) AS oos_count, sum(signal_count) AS signal_count FROM monthly
    UNION ALL
    SELECT 'shift_instance', sum(measurement_count), sum(oos_count), sum(signal_count) FROM instances
    UNION ALL
    SELECT 'shift_type', sum(measurement_count), sum(oos_count), sum(signal_count) FROM types
)
SELECT grouped.*, overall.*
FROM grouped CROSS JOIN overall
WHERE grouped.measurement_count <> overall.measurement_count
   OR grouped.oos_count <> overall.oos_count
   OR grouped.signal_count <> overall.signal_count;

-- 5. Rates use their own grouping denominator; no duplicate/missing IDs.
WITH base AS (
    SELECT * FROM v_drift_shift_measurements_booth01_a_l1
), scoped AS (
    SELECT 'MONTH' AS scope, production_month::text AS group_key,
           count(*) AS measurement_count, count(*) FILTER (WHERE is_oos) AS oos_count,
           count(*) FILTER (WHERE spc_signal) AS signal_count
    FROM base GROUP BY production_month
    UNION ALL
    SELECT 'SHIFT_INSTANCE', shift_instance::text, count(*), count(*) FILTER (WHERE is_oos),
           count(*) FILTER (WHERE spc_signal) FROM base GROUP BY shift_instance
    UNION ALL
    SELECT 'SHIFT_TYPE', shift_id::text, count(*), count(*) FILTER (WHERE is_oos),
           count(*) FILTER (WHERE spc_signal) FROM base GROUP BY shift_id
)
SELECT *
FROM scoped
WHERE measurement_count <= 0
   OR oos_count::numeric / measurement_count NOT BETWEEN 0 AND 1
   OR signal_count::numeric / measurement_count NOT BETWEEN 0 AND 1;

-- 6. Shift-decomposition identity using the raw canonical input.
WITH base AS (
    SELECT measured_value, shift_instance
    FROM v_drift_shift_measurements_booth01_a_l1
), overall AS (
    SELECT avg(measured_value) AS overall_mean FROM base
), instance_stats AS (
    SELECT shift_instance, count(*) AS n, avg(measured_value) AS group_mean,
           coalesce(stddev_samp(measured_value), 0) ^ 2 * greatest(count(*) - 1, 0) AS within_ss
    FROM base
    GROUP BY shift_instance
), sums AS (
    SELECT
        (SELECT sum((measured_value - overall_mean) ^ 2) FROM base CROSS JOIN overall) AS total_ss,
        sum(within_ss) AS within_ss,
        sum(n * (group_mean - (SELECT overall_mean FROM overall)) ^ 2) AS between_ss
    FROM instance_stats
)
SELECT *
FROM sums
WHERE abs(total_ss - within_ss - between_ss) > 0.000001;
