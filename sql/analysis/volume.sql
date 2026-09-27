-- Production volume at date/shift/booth grain.
SELECT *
FROM v_production_volume
ORDER BY production_date, shift_id, booth_id;

-- Cabin counts per batch; expected to be five cabins per generated batch.
SELECT batch_id, booth_name, shift_name, cabin_count, measurement_count
FROM v_batch_quality
ORDER BY batch_id;