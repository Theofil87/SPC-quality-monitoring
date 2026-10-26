-- Returns failing cabin IDs only.
select
    cabin_id,
    count(*) as measurement_count,
    count(distinct measurement_point_id) as measurement_point_count
from {{ ref('stg_quality_measurements') }}
group by cabin_id
having count(*) <> 18
    or count(distinct measurement_point_id) <> 18
