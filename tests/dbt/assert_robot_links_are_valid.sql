-- Returns bridge rows with broken booth consistency or duplicate pairs only.
with bridge as (
    select
        link.measurement_id,
        link.robot_id,
        measurement.booth_id as measurement_booth_id,
        axis.booth_id as robot_booth_id,
        count(*) over (partition by link.measurement_id, link.robot_id) as duplicate_pair_count
    from {{ source('paintshop', 'bridge_measurement_robot') }} as link
    join {{ ref('stg_quality_measurements') }} as measurement using (measurement_id)
    join {{ source('paintshop', 'dim_robot') }} as robot using (robot_id)
    join {{ source('paintshop', 'dim_track_axis') }} as axis using (track_axis_id)
)
select *
from bridge
where measurement_booth_id <> robot_booth_id
   or duplicate_pair_count <> 1
