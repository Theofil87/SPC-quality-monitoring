\set ON_ERROR_STOP on

DO $$
BEGIN
    IF EXISTS (
        WITH spc AS MATERIALIZED (
            SELECT * FROM v_spc_rule_results_booth01_a_l1
        ), input AS MATERIALIZED (
            SELECT * FROM v_capability_measurements_booth01_a_l1
        ), source AS MATERIALIZED (
            SELECT measurement.measurement_id, measurement.is_oos,
                   spc.spc_signal, spc.baseline_id, spc.spc_evaluation_status
            FROM v_measurement_enriched AS measurement
            JOIN spc USING (measurement_id)
            WHERE measurement.booth_name = 'BOOTH_01'
              AND measurement.point_code = 'A-L1'
              AND measurement.characteristic = 'Coating Thickness'
              AND measurement.unit = 'um'
              AND measurement.lsl = 70 AND measurement.target = 75 AND measurement.usl = 80
        )
        SELECT 1
        FROM input FULL JOIN source USING (measurement_id)
        WHERE source.measurement_id IS NULL OR input.measurement_id IS NULL
           OR input.is_oos IS DISTINCT FROM source.is_oos
           OR input.spc_signal IS DISTINCT FROM source.spc_signal
           OR input.baseline_id IS DISTINCT FROM source.baseline_id
           OR input.spc_evaluation_status IS DISTINCT FROM source.spc_evaluation_status
    ) OR EXISTS (
        SELECT 1 FROM v_capability_measurements_booth01_a_l1
        GROUP BY measurement_id HAVING count(*) <> 1
    ) THEN
        RAISE EXCEPTION 'Capability input does not reconcile with source measurements and SPC coverage';
    END IF;
END
$$;

-- Reconcile the capability input view to the measurement-level source and SPC flags.
WITH spc AS MATERIALIZED (
    SELECT * FROM v_spc_rule_results_booth01_a_l1
), source AS MATERIALIZED (
    SELECT
        measurement.measurement_id,
        measurement.is_oos,
        spc.spc_signal
    FROM v_measurement_enriched AS measurement
    JOIN spc USING (measurement_id)
    WHERE measurement.booth_name = 'BOOTH_01'
      AND measurement.point_code = 'A-L1'
      AND measurement.characteristic = 'Coating Thickness'
      AND measurement.unit = 'um'
      AND measurement.lsl = 70
      AND measurement.target = 75
      AND measurement.usl = 80
), capability_input AS MATERIALIZED (
    SELECT *
    FROM v_capability_measurements_booth01_a_l1
), comparison AS (
    SELECT
        (SELECT count(*) FROM source) AS source_count,
        (SELECT count(*) FROM capability_input) AS input_count,
        (SELECT count(DISTINCT measurement_id) FROM capability_input) AS distinct_input_count,
        (SELECT count(*) FILTER (WHERE is_oos) FROM source) AS source_oos_count,
        (SELECT count(*) FILTER (WHERE is_oos) FROM capability_input) AS input_oos_count,
        (SELECT count(*) FILTER (WHERE spc_signal) FROM source) AS source_signal_count,
        (SELECT count(*) FILTER (WHERE spc_signal) FROM capability_input) AS input_signal_count
)
SELECT
    source_count,
    input_count,
    distinct_input_count,
    source_oos_count,
    input_oos_count,
    source_oos_count::numeric / nullif(source_count, 0) AS source_oos_rate,
    input_oos_count::numeric / nullif(input_count, 0) AS input_oos_rate,
    source_signal_count,
    input_signal_count,
    CASE
        WHEN source_count = input_count
         AND input_count = distinct_input_count
         AND source_oos_count = input_oos_count
         AND source_signal_count = input_signal_count
            THEN 'PASS'
        ELSE 'FAIL'
    END AS reconciliation_status
FROM comparison;