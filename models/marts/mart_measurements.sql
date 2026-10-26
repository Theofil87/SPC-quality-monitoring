-- Conformed measurement-grain mart for downstream analysis and dashboards.
select *
from {{ ref('stg_quality_measurements') }}
