-- Reuses immutable SQL SPC results. No events are used and no rules are reimplemented.
select
    measurement.measurement_id,
    measurement.production_date,
    measurement.booth_name,
    measurement.point_code,
    measurement.characteristic,
    measurement.unit,
    measurement.measured_value,
    measurement.is_oos,
    spc.shift_instance,
    spc.shift_id,
    spc.shift_name,
    spc.rule_1,
    spc.rule_2,
    spc.rule_3,
    spc.rule_4,
    spc.spc_signal
from {{ ref('mart_measurements') }} as measurement
join {{ source('paintshop', 'v_spc_rule_results_booth01_a_l1') }} as spc
    using (measurement_id)
where measurement.booth_name = 'BOOTH_01'
  and measurement.point_code = 'A-L1'
  and measurement.characteristic = 'Coating Thickness'
  and measurement.unit = 'um'
