\set ON_ERROR_STOP on

SELECT 'dim_booth' AS table_name, COUNT(*) AS row_count FROM dim_booth
UNION ALL SELECT 'dim_track_axis', COUNT(*) FROM dim_track_axis
UNION ALL SELECT 'dim_robot', COUNT(*) FROM dim_robot
UNION ALL SELECT 'dim_shift', COUNT(*) FROM dim_shift
UNION ALL SELECT 'dim_batch', COUNT(*) FROM dim_batch
UNION ALL SELECT 'dim_cabin', COUNT(*) FROM dim_cabin
UNION ALL SELECT 'dim_measurement_point', COUNT(*) FROM dim_measurement_point
UNION ALL SELECT 'dim_specification', COUNT(*) FROM dim_specification
UNION ALL SELECT 'fact_quality_measurement', COUNT(*) FROM fact_quality_measurement
UNION ALL SELECT 'bridge_measurement_robot', COUNT(*) FROM bridge_measurement_robot
UNION ALL SELECT 'fact_process_event', COUNT(*) FROM fact_process_event
ORDER BY table_name;

DO $$
DECLARE
	table_target RECORD;
	staged_count BIGINT;
	loaded_count BIGINT;
	violation_count BIGINT;
BEGIN
	IF to_regclass('pg_temp.stg_dim_booth') IS NOT NULL THEN
		FOR table_target IN
			SELECT * FROM (VALUES
				('stg_dim_booth', 'dim_booth'),
				('stg_dim_track_axis', 'dim_track_axis'),
				('stg_dim_robot', 'dim_robot'),
				('stg_dim_shift', 'dim_shift'),
				('stg_dim_batch', 'dim_batch'),
				('stg_dim_cabin', 'dim_cabin'),
				('stg_dim_measurement_point', 'dim_measurement_point'),
				('stg_dim_specification', 'dim_specification'),
				('stg_fact_quality_measurement', 'fact_quality_measurement'),
				('stg_bridge_measurement_robot', 'bridge_measurement_robot'),
				('stg_fact_process_event', 'fact_process_event')
			) AS tables(stage_name, target_name)
		LOOP
			EXECUTE format('SELECT count(*) FROM pg_temp.%I', table_target.stage_name)
				INTO staged_count;
			EXECUTE format('SELECT count(*) FROM %I', table_target.target_name)
				INTO loaded_count;
			IF staged_count <> loaded_count THEN
				RAISE EXCEPTION 'CSV/database row-count mismatch for %: staged %, loaded %',
					table_target.target_name, staged_count, loaded_count;
			END IF;
		END LOOP;
	END IF;

	IF (SELECT count(*) FROM dim_booth) <> 2
	   OR (SELECT count(*) FROM dim_track_axis) <> 4
	   OR (SELECT count(*) FROM dim_robot) <> 8
	   OR (SELECT count(*) FROM dim_shift) <> 3
	   OR (SELECT count(*) FROM dim_measurement_point) <> 18
	   OR (SELECT count(*) FROM dim_specification) <> 1 THEN
		RAISE EXCEPTION 'Reference dimension counts do not match the generated dataset contract';
	END IF;

	SELECT count(*) INTO violation_count
	FROM (
		SELECT cabin.cabin_id
		FROM dim_cabin AS cabin
		LEFT JOIN fact_quality_measurement AS measurement USING (cabin_id)
		GROUP BY cabin.cabin_id
		HAVING count(measurement.measurement_id) <> 18
			OR count(DISTINCT measurement.measurement_point_id) <> 18
	) AS invalid_cabins;
	IF violation_count > 0 OR (SELECT count(*) FROM dim_cabin) = 0 THEN
		RAISE EXCEPTION 'Each cabin must have exactly 18 measurements at 18 distinct points';
	END IF;

	SELECT count(*) INTO violation_count
	FROM (
		SELECT measurement.measurement_id
		FROM fact_quality_measurement AS measurement
		LEFT JOIN bridge_measurement_robot AS bridge USING (measurement_id)
		GROUP BY measurement.measurement_id
		HAVING count(bridge.robot_id) NOT BETWEEN 1 AND 4
	) AS invalid_measurements;
	IF violation_count > 0 THEN
		RAISE EXCEPTION 'Each measurement must have between 1 and 4 contributing robots';
	END IF;

	SELECT count(DISTINCT robot_count) INTO violation_count
	FROM (
		SELECT measurement_id, count(*) AS robot_count
		FROM bridge_measurement_robot
		GROUP BY measurement_id
	) AS contribution_counts;
	IF violation_count < 2 THEN
		RAISE EXCEPTION 'Robot contribution count must vary across measurements';
	END IF;

	SELECT count(*) INTO violation_count
	FROM bridge_measurement_robot AS bridge
	JOIN fact_quality_measurement AS measurement USING (measurement_id)
	JOIN dim_cabin AS cabin USING (cabin_id)
	JOIN dim_robot AS robot USING (robot_id)
	JOIN dim_track_axis AS axis USING (track_axis_id)
	WHERE cabin.booth_id <> axis.booth_id;
	IF violation_count > 0 THEN
		RAISE EXCEPTION 'A contributing robot must belong to the cabin booth';
	END IF;

	SELECT count(*) INTO violation_count
	FROM (
		SELECT bridge.measurement_id
		FROM bridge_measurement_robot AS bridge
		JOIN dim_robot AS robot USING (robot_id)
		GROUP BY bridge.measurement_id
		HAVING count(DISTINCT robot.track_axis_id) > 1
	) AS cross_track_measurements;
	IF violation_count = 0 THEN
		RAISE EXCEPTION 'Expected at least one synthetic measurement with contributors from different track axes';
	END IF;

	SELECT count(*) INTO violation_count
	FROM dim_cabin AS cabin
	JOIN dim_batch AS batch USING (batch_id)
	JOIN fact_quality_measurement AS measurement USING (cabin_id)
	WHERE measurement.measurement_timestamp <> cabin.production_timestamp
	   OR measurement.unit <> (
			SELECT specification.unit
			FROM dim_specification AS specification
			WHERE specification.specification_id = measurement.specification_id
	   );
	IF violation_count > 0 THEN
		RAISE EXCEPTION 'Measurement timestamp or unit does not match its cabin/specification';
	END IF;

	SELECT count(*) INTO violation_count
	FROM (
		SELECT batch_id
		FROM dim_cabin
		GROUP BY batch_id
		HAVING count(DISTINCT booth_id) <> 1
	) AS batches_with_multiple_booths;
	IF violation_count > 0 THEN
		RAISE EXCEPTION 'All cabins in a batch must belong to exactly one booth';
	END IF;

	SELECT count(*) INTO violation_count
	FROM (
		SELECT batch.batch_id
		FROM dim_batch AS batch
		LEFT JOIN dim_cabin AS cabin USING (batch_id)
		GROUP BY batch.batch_id, batch.batch_start, batch.batch_end
		HAVING count(cabin.cabin_id) <> 5
			OR count(cabin.cabin_id) FILTER (
				WHERE cabin.production_timestamp < batch.batch_start
				   OR cabin.production_timestamp > batch.batch_end
			) > 0
	) AS invalid_batch_cabins;
	IF violation_count > 0 THEN
		RAISE EXCEPTION 'Each batch must contain five cabins with production timestamps inside its batch window';
	END IF;

	SELECT count(*) INTO violation_count
	FROM fact_process_event AS event
	JOIN dim_batch AS batch USING (batch_id)
	WHERE event.event_timestamp <> batch.batch_start
	   OR NOT EXISTS (
			SELECT 1
			FROM dim_cabin AS cabin
			WHERE cabin.batch_id = event.batch_id
			  AND cabin.booth_id = event.booth_id
	   );
	IF violation_count > 0 THEN
		RAISE EXCEPTION 'Process event booth or timestamp does not match its batch';
	END IF;

	SELECT count(*) INTO violation_count
	FROM dim_booth AS booth
	WHERE (
		SELECT count(DISTINCT robot.robot_id)
		FROM dim_robot AS robot
		JOIN dim_track_axis AS axis USING (track_axis_id)
		WHERE axis.booth_id = booth.booth_id
	) <> 4;
	IF violation_count > 0 THEN
		RAISE EXCEPTION 'Each booth must have four robots available for simultaneous operation';
	END IF;
END
$$;