-- Daily booth quality metrics. Rates use measurement count as denominator.
select
    production_date,
    booth_id,
    booth_name,
    count(*) as measurement_count,
    count(distinct batch_id) as batch_count,
    count(distinct cabin_id) as cabin_count,
    avg(measured_value) as mean_thickness,
    stddev_samp(measured_value) as stddev_thickness,
    avg(deviation_from_target) as mean_deviation_from_target,
    count(*) filter (where below_lsl) as below_lsl_count,
    count(*) filter (where above_usl) as above_usl_count,
    count(*) filter (where is_oos) as oos_count,
    count(*) filter (where is_oos)::numeric / nullif(count(*), 0) as oos_rate
from {{ ref('mart_measurements') }}
group by production_date, booth_id, booth_name
