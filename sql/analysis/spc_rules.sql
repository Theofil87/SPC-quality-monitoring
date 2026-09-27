-- First-pass I-MR SPC rules for BOOTH_01 / A-L1.
-- The control-limit baseline is exploratory Phase I and uses all selected
-- observations. Process-event records and specification limits are not inputs.
WITH source AS (
    SELECT
        measurement.measurement_id,
        measurement.booth_id,
        measurement.booth_name,
        measurement.measurement_point_id,
        measurement.point_code,
        measurement.specification_id,
        measurement.shift_id,
        measurement.shift_name,
        measurement.batch_start,
        measurement.measurement_timestamp,
        measurement.measured_value,
        (
            (measurement.batch_start::date + shift.start_time)
            - CASE
                WHEN shift.end_time <= shift.start_time
                 AND measurement.batch_start::time < shift.start_time
                    THEN interval '1 day'
                ELSE interval '0 day'
              END
        ) AS shift_instance_start
    FROM v_measurement_enriched AS measurement
    JOIN dim_shift AS shift USING (shift_id)
    WHERE measurement.booth_name = 'BOOTH_01'
      AND measurement.point_code = 'A-L1'
), ordered AS (
    SELECT
        source.*,
        row_number() OVER stream_order AS observation_number,
        lag(measured_value) OVER stream_order AS previous_value
    FROM source
    WINDOW stream_order AS (
        PARTITION BY
            booth_id,
            measurement_point_id,
            specification_id,
            shift_id,
            shift_instance_start
        ORDER BY measurement_timestamp, measurement_id
    )
), moving_ranges AS (
    SELECT
        ordered.*,
        CASE
            WHEN previous_value IS NULL THEN NULL
            ELSE abs(measured_value - previous_value)
        END AS moving_range
    FROM ordered
), baseline AS (
    SELECT
        booth_id,
        measurement_point_id,
        specification_id,
        avg(measured_value) AS center_line,
        avg(moving_range) / 1.128 AS sigma
    FROM moving_ranges
    GROUP BY booth_id, measurement_point_id, specification_id
), zoned AS (
    SELECT
        moving_ranges.*,
        baseline.center_line,
        baseline.sigma,
        baseline.center_line - 3 * baseline.sigma AS lcl,
        baseline.center_line + 3 * baseline.sigma AS ucl,
        CASE WHEN moving_ranges.measured_value > baseline.center_line THEN 1
             WHEN moving_ranges.measured_value < baseline.center_line THEN -1
             ELSE 0
        END AS center_line_side,
        CASE WHEN moving_ranges.measured_value > baseline.center_line + 2 * baseline.sigma THEN 1 ELSE 0 END AS above_2_sigma,
        CASE WHEN moving_ranges.measured_value < baseline.center_line - 2 * baseline.sigma THEN 1 ELSE 0 END AS below_2_sigma,
        CASE WHEN moving_ranges.measured_value > baseline.center_line + baseline.sigma THEN 1 ELSE 0 END AS above_1_sigma,
        CASE WHEN moving_ranges.measured_value < baseline.center_line - baseline.sigma THEN 1 ELSE 0 END AS below_1_sigma
    FROM moving_ranges
    JOIN baseline USING (booth_id, measurement_point_id, specification_id)
), rule_windows AS (
    SELECT
        zoned.*,
        sum(above_2_sigma) OVER shift_order_3 AS above_2_in_3,
        sum(below_2_sigma) OVER shift_order_3 AS below_2_in_3,
        sum(above_1_sigma) OVER shift_order_5 AS above_1_in_5,
        sum(below_1_sigma) OVER shift_order_5 AS below_1_in_5,
        lag(center_line_side, 1, 0) OVER shift_order AS previous_center_line_side
    FROM zoned
    WINDOW
        shift_order AS (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start
            ORDER BY measurement_timestamp, measurement_id
        ),
        shift_order_3 AS (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start
            ORDER BY measurement_timestamp, measurement_id
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ),
        shift_order_5 AS (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start
            ORDER BY measurement_timestamp, measurement_id
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        )
), rule_runs AS (
    SELECT
        rule_windows.*,
        sum(CASE WHEN center_line_side <> previous_center_line_side THEN 1 ELSE 0 END)
            OVER (
                PARTITION BY
                    booth_id,
                    measurement_point_id,
                    specification_id,
                    shift_id,
                    shift_instance_start
                ORDER BY measurement_timestamp, measurement_id
            ) AS center_line_run_id
    FROM rule_windows
), rule_run_lengths AS (
    SELECT
        rule_runs.*,
        count(*) OVER (
            PARTITION BY
                booth_id,
                measurement_point_id,
                specification_id,
                shift_id,
                shift_instance_start,
                center_line_run_id
            ORDER BY measurement_timestamp, measurement_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS center_line_run_length
    FROM rule_runs
), signals AS (
    SELECT
        rule_run_lengths.*,
        (measured_value > ucl OR measured_value < lcl) AS rule_1,
        (observation_number >= 3 AND (above_2_in_3 >= 2 OR below_2_in_3 >= 2)) AS rule_2,
        (observation_number >= 5 AND (above_1_in_5 >= 4 OR below_1_in_5 >= 4)) AS rule_3,
        (center_line_side <> 0 AND center_line_run_length >= 8) AS rule_4
    FROM rule_run_lengths
)
SELECT
    measurement_timestamp,
    measurement_id,
    booth_name AS booth,
    point_code AS measurement_point,
    shift_id,
    shift_name,
    shift_instance_start AS shift_instance,
    measured_value,
    moving_range,
    center_line,
    sigma,
    lcl,
    ucl,
    rule_1,
    rule_2,
    rule_3,
    rule_4,
    (rule_1 OR rule_2 OR rule_3 OR rule_4) AS spc_signal
FROM signals
ORDER BY measurement_timestamp, measurement_id;