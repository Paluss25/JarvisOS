-- Keep manually merged Garmin recovery rows visible to WHOOP/Garmin validation.
-- COH photo ingestion writes the canonical recovery_metrics row directly; the
-- validation view reads daily_recovery_observations.

CREATE OR REPLACE FUNCTION sync_garmin_recovery_observation()
RETURNS TRIGGER AS $$
BEGIN
    IF COALESCE(NEW.source, '') = 'whoop_api_v2' THEN
        RETURN NEW;
    END IF;

    INSERT INTO daily_recovery_observations
        (date, user_id, source, rhr_overnight, hrv_overnight_avg,
         sleep_duration_min, sleep_score, sleep_deep_min, sleep_rem_min,
         sleep_light_min, sleep_awake_min, steps, distance_km, active_kcal,
         active_min, data_quality, raw_json, updated_at)
    VALUES
        (NEW.date, NEW.user_id, 'garmin_fit_daily', NEW.rhr_overnight,
         NEW.hrv_overnight_avg, NEW.sleep_duration_min, NEW.sleep_score,
         NEW.sleep_deep_min, NEW.sleep_rem_min, NEW.sleep_light_min,
         NEW.sleep_awake_min, NEW.steps, NEW.distance_km, NEW.active_kcal,
         NEW.active_min, COALESCE(NEW.data_quality, 'ok'),
         jsonb_build_object(
             'source_table', 'recovery_metrics',
             'recovery_metrics_id', NEW.id,
             'recovery_metrics_source', NEW.source
         ),
         now())
    ON CONFLICT (date, user_id, source) DO UPDATE SET
        rhr_overnight = EXCLUDED.rhr_overnight,
        hrv_overnight_avg = EXCLUDED.hrv_overnight_avg,
        sleep_duration_min = EXCLUDED.sleep_duration_min,
        sleep_score = EXCLUDED.sleep_score,
        sleep_deep_min = EXCLUDED.sleep_deep_min,
        sleep_rem_min = EXCLUDED.sleep_rem_min,
        sleep_light_min = EXCLUDED.sleep_light_min,
        sleep_awake_min = EXCLUDED.sleep_awake_min,
        steps = EXCLUDED.steps,
        distance_km = EXCLUDED.distance_km,
        active_kcal = EXCLUDED.active_kcal,
        active_min = EXCLUDED.active_min,
        data_quality = EXCLUDED.data_quality,
        raw_json = EXCLUDED.raw_json,
        updated_at = now();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_garmin_recovery_observation ON recovery_metrics;

CREATE TRIGGER trg_sync_garmin_recovery_observation
AFTER INSERT OR UPDATE ON recovery_metrics
FOR EACH ROW
EXECUTE FUNCTION sync_garmin_recovery_observation();

CREATE OR REPLACE FUNCTION sync_garmin_recovery_observation_existing()
RETURNS INTEGER AS $$
DECLARE
    synced_count INTEGER;
BEGIN
    WITH latest_garmin AS (
        SELECT DISTINCT ON (date, user_id)
            id, date, user_id, source, rhr_overnight, hrv_overnight_avg,
            sleep_duration_min, sleep_score, sleep_deep_min, sleep_rem_min,
            sleep_light_min, sleep_awake_min, steps, distance_km, active_kcal,
            active_min, data_quality
        FROM recovery_metrics
        WHERE COALESCE(source, '') <> 'whoop_api_v2'
        ORDER BY date, user_id, updated_at DESC NULLS LAST, id DESC
    ),
    upserted AS (
        INSERT INTO daily_recovery_observations
            (date, user_id, source, rhr_overnight, hrv_overnight_avg,
             sleep_duration_min, sleep_score, sleep_deep_min, sleep_rem_min,
             sleep_light_min, sleep_awake_min, steps, distance_km, active_kcal,
             active_min, data_quality, raw_json, updated_at)
        SELECT
            date, user_id, 'garmin_fit_daily', rhr_overnight,
            hrv_overnight_avg, sleep_duration_min, sleep_score,
            sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
            steps, distance_km, active_kcal, active_min,
            COALESCE(data_quality, 'ok'),
            jsonb_build_object(
                'source_table', 'recovery_metrics',
                'recovery_metrics_id', id,
                'recovery_metrics_source', source
            ),
            now()
        FROM latest_garmin
        ON CONFLICT (date, user_id, source) DO UPDATE SET
            rhr_overnight = EXCLUDED.rhr_overnight,
            hrv_overnight_avg = EXCLUDED.hrv_overnight_avg,
            sleep_duration_min = EXCLUDED.sleep_duration_min,
            sleep_score = EXCLUDED.sleep_score,
            sleep_deep_min = EXCLUDED.sleep_deep_min,
            sleep_rem_min = EXCLUDED.sleep_rem_min,
            sleep_light_min = EXCLUDED.sleep_light_min,
            sleep_awake_min = EXCLUDED.sleep_awake_min,
            steps = EXCLUDED.steps,
            distance_km = EXCLUDED.distance_km,
            active_kcal = EXCLUDED.active_kcal,
            active_min = EXCLUDED.active_min,
            data_quality = EXCLUDED.data_quality,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        RETURNING 1
    )
    SELECT count(*) INTO synced_count FROM upserted;

    RETURN synced_count;
END;
$$ LANGUAGE plpgsql;

SELECT sync_garmin_recovery_observation_existing();

DO $$
BEGIN
    IF to_regrole('roger') IS NOT NULL THEN
        GRANT EXECUTE ON FUNCTION sync_garmin_recovery_observation() TO roger;
        GRANT EXECUTE ON FUNCTION sync_garmin_recovery_observation_existing() TO roger;
    END IF;
    IF to_regrole('drhouse') IS NOT NULL THEN
        GRANT EXECUTE ON FUNCTION sync_garmin_recovery_observation() TO drhouse;
        GRANT EXECUTE ON FUNCTION sync_garmin_recovery_observation_existing() TO drhouse;
    END IF;
END $$;
