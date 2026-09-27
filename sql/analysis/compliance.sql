-- Measurement-level lower/upper specification compliance.
SELECT
    compliance_status,
    count(*) AS measurement_count,
    count(*)::numeric / sum(count(*)) OVER () AS measurement_rate
FROM v_measurement_enriched
GROUP BY compliance_status
ORDER BY compliance_status;

-- Cabin-level OOS rate: a cabin is OOS if any of its measurements are OOS.
SELECT
    count(*) AS cabin_count,
    count(*) FILTER (WHERE oos_count > 0) AS cabins_with_oos,
    count(*) FILTER (WHERE oos_count > 0)::numeric / nullif(count(*), 0) AS cabin_oos_rate
FROM v_cabin_quality;

SELECT booth_name, production_date, measurement_count, oos_count, oos_rate
FROM v_booth_quality_daily
WHERE oos_count > 0
ORDER BY production_date, booth_name;