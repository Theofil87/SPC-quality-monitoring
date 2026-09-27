-- Retrospective descriptive comparison against synthetic event ground truth.
-- Never use fact_process_event or this query as an SPC detection input.
SELECT
    event_type,
    severity,
    booth_name,
    count(DISTINCT batch_id) AS affected_batch_count,
    sum(measurement_count) AS affected_measurement_count,
    avg(mean_thickness) AS mean_of_batch_means,
    avg(stddev_thickness) AS mean_batch_stddev,
    sum(oos_count) AS oos_measurement_count
FROM v_event_evaluation_context
GROUP BY event_type, severity, booth_name
ORDER BY event_type, booth_name;

-- Inspect event-affected batch records at their event/batch grain.
SELECT *
FROM v_event_evaluation_context
ORDER BY event_timestamp, event_id;

-- Compare descriptive batch metrics around recorded affected-batch periods.
-- The event table has no event-window ID; repeated identical event descriptions
-- at one booth can merge into one period, so review period_start/period_end.
WITH event_periods AS (
    SELECT
        event_type,
        severity,
        booth_id,
        booth_name,
        description,
        min(event_timestamp)::date AS period_start,
        max(event_timestamp)::date AS period_end
    FROM v_event_evaluation_context
    GROUP BY event_type, severity, booth_id, booth_name, description
), comparison AS (
    SELECT
        event_periods.event_type,
        event_periods.severity,
        event_periods.booth_name,
        event_periods.period_start,
        event_periods.period_end,
        CASE
            WHEN batch.batch_start::date < event_periods.period_start THEN 'BEFORE'
            WHEN batch.batch_start::date > event_periods.period_end THEN 'AFTER'
            ELSE 'DURING'
        END AS relative_period,
        batch.mean_thickness,
        batch.stddev_thickness,
        batch.oos_count,
        batch.measurement_count
    FROM event_periods
    JOIN v_batch_quality AS batch
        ON batch.booth_id = event_periods.booth_id
       AND batch.batch_start::date BETWEEN event_periods.period_start - 7
                                      AND event_periods.period_end + 7
)
SELECT
    event_type,
    severity,
    booth_name,
    period_start,
    period_end,
    relative_period,
    count(*) AS batch_count,
    sum(measurement_count) AS measurement_count,
    avg(mean_thickness) AS mean_of_batch_means,
    avg(stddev_thickness) AS mean_batch_stddev,
    sum(oos_count) AS oos_measurement_count
FROM comparison
GROUP BY event_type, severity, booth_name, period_start, period_end, relative_period
ORDER BY period_start, event_type, booth_name, relative_period;