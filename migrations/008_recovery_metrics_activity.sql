BEGIN;

ALTER TABLE recovery_metrics
    ADD COLUMN IF NOT EXISTS steps        INTEGER,
    ADD COLUMN IF NOT EXISTS distance_km  NUMERIC,
    ADD COLUMN IF NOT EXISTS active_kcal  INTEGER,
    ADD COLUMN IF NOT EXISTS active_min   NUMERIC,
    ADD COLUMN IF NOT EXISTS data_quality TEXT NOT NULL DEFAULT 'ok';

COMMENT ON COLUMN recovery_metrics.data_quality IS
    'ok | stress_high_suspect | incomplete — set by import when data quality issues are detected';

DROP VIEW IF EXISTS daily_fitness_enriched;

CREATE VIEW daily_fitness_enriched AS
WITH files AS (
    SELECT date, user_id, count(*) AS daily_fit_file_count
    FROM daily_fit_files
    GROUP BY date, user_id
),
wellness AS (
    SELECT
        date,
        user_id,
        min(heart_rate) FILTER (WHERE heart_rate > 0) AS min_wellness_hr,
        avg(heart_rate) FILTER (WHERE heart_rate > 0) AS avg_wellness_hr,
        max(steps)           AS latest_steps,
        max(active_calories) AS latest_active_calories,
        max(distance_m)      AS latest_distance_m,
        max(duration_min)    AS latest_active_min
    FROM daily_wellness_records
    GROUP BY date, user_id
),
skin AS (
    SELECT DISTINCT ON (date, user_id)
        date,
        user_id,
        average_deviation_c          AS skin_average_deviation_c,
        average_7_day_deviation_c    AS skin_average_7_day_deviation_c,
        nightly_value_c              AS skin_nightly_value_c
    FROM daily_skin_temp_overnight
    ORDER BY date, user_id, id DESC
)
SELECT
    COALESCE(r.date, f.date)       AS date,
    COALESCE(r.user_id, f.user_id) AS user_id,
    f.daily_fit_file_count,
    r.body_battery_am,
    r.body_battery_pm,
    r.stress_avg,
    r.stress_max,
    r.hrv_overnight_avg,
    r.hrv_status,
    r.sleep_duration_min,
    r.sleep_score,
    r.sleep_deep_min,
    r.sleep_rem_min,
    r.sleep_light_min,
    r.sleep_awake_min,
    r.rhr_overnight,
    COALESCE(r.steps,       w.latest_steps)           AS steps,
    COALESCE(r.distance_km, w.latest_distance_m/1000) AS distance_km,
    COALESCE(r.active_kcal, w.latest_active_calories) AS active_kcal,
    COALESCE(r.active_min,  w.latest_active_min)      AS active_min,
    r.data_quality,
    w.min_wellness_hr,
    w.avg_wellness_hr,
    s.skin_average_deviation_c,
    s.skin_average_7_day_deviation_c,
    s.skin_nightly_value_c
FROM recovery_metrics r
FULL OUTER JOIN files f   ON f.date = r.date AND f.user_id = r.user_id
LEFT JOIN wellness w       ON w.date = COALESCE(r.date, f.date) AND w.user_id = COALESCE(r.user_id, f.user_id)
LEFT JOIN skin s           ON s.date = COALESCE(r.date, f.date) AND s.user_id = COALESCE(r.user_id, f.user_id);

DO $$
BEGIN
    IF to_regrole('drhouse') IS NOT NULL THEN
        GRANT SELECT ON daily_fitness_enriched TO drhouse;
    END IF;
END
$$;

COMMIT;
