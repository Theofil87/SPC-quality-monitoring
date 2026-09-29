-- One row per selected measurement; capability formulas are calculated in Python.
-- Apply sql/views.sql before running this query so the reusable input view exists.
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
    below_lsl,
    above_usl,
    is_oos,
    rule_1,
    rule_2,
    rule_3,
    rule_4,
    spc_signal
FROM v_capability_measurements_booth01_a_l1
ORDER BY measurement_timestamp, measurement_id;