-- One measurement per row: canonical input contract for drift and
-- shift-to-shift variation analysis. No event table is used.
SELECT
    measurement_id,
    measurement_timestamp,
    production_timestamp,
    production_month,
    shift_instance,
    shift_id,
    shift_name,
    booth,
    measurement_point,
    characteristic,
    unit,
    lsl,
    target,
    usl,
    measured_value,
    deviation_from_target,
    below_lsl,
    above_usl,
    is_oos,
    rule_1,
    rule_2,
    rule_3,
    rule_4,
    spc_signal
FROM v_drift_shift_measurements_booth01_a_l1
ORDER BY shift_instance, measurement_timestamp, measurement_id;
