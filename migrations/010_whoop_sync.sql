BEGIN;

CREATE TABLE IF NOT EXISTS whoop_sync_runs (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            INTEGER NOT NULL REFERENCES users(id),
    date_from          DATE NOT NULL,
    date_to            DATE NOT NULL,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    status             TEXT NOT NULL DEFAULT 'running',
    recoveries_seen    INTEGER NOT NULL DEFAULT 0,
    sleeps_seen        INTEGER NOT NULL DEFAULT 0,
    cycles_seen        INTEGER NOT NULL DEFAULT 0,
    workouts_seen      INTEGER NOT NULL DEFAULT 0,
    error_message      TEXT
);

CREATE INDEX IF NOT EXISTS idx_whoop_sync_runs_user_dates
    ON whoop_sync_runs(user_id, date_from, date_to, started_at DESC);

CREATE TABLE IF NOT EXISTS whoop_recoveries (
    cycle_id             BIGINT NOT NULL,
    sleep_id             TEXT,
    user_id              INTEGER NOT NULL REFERENCES users(id),
    whoop_user_id        BIGINT,
    score_state          TEXT NOT NULL,
    recovery_score       INTEGER,
    resting_heart_rate   INTEGER,
    hrv_rmssd_milli      NUMERIC,
    spo2_percentage      NUMERIC,
    skin_temp_celsius    NUMERIC,
    raw_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cycle_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_whoop_recoveries_sleep_id
    ON whoop_recoveries(sleep_id);

CREATE TABLE IF NOT EXISTS whoop_sleeps (
    sleep_id             TEXT NOT NULL,
    cycle_id             BIGINT,
    user_id              INTEGER NOT NULL REFERENCES users(id),
    whoop_user_id        BIGINT,
    start_at             TIMESTAMPTZ,
    end_at               TIMESTAMPTZ,
    timezone_offset      TEXT,
    nap                  BOOLEAN,
    score_state          TEXT,
    sleep_duration_min   INTEGER,
    sleep_score          INTEGER,
    sleep_deep_min       INTEGER,
    sleep_rem_min        INTEGER,
    sleep_light_min      INTEGER,
    sleep_awake_min      INTEGER,
    respiratory_rate     NUMERIC,
    raw_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sleep_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_whoop_sleeps_user_end
    ON whoop_sleeps(user_id, end_at DESC);

CREATE TABLE IF NOT EXISTS whoop_cycles (
    cycle_id             BIGINT NOT NULL,
    user_id              INTEGER NOT NULL REFERENCES users(id),
    whoop_user_id        BIGINT,
    start_at             TIMESTAMPTZ,
    end_at               TIMESTAMPTZ,
    timezone_offset      TEXT,
    score_state          TEXT,
    strain               NUMERIC,
    average_heart_rate   INTEGER,
    max_heart_rate       INTEGER,
    kilojoule            NUMERIC,
    raw_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cycle_id, user_id)
);

CREATE TABLE IF NOT EXISTS whoop_workouts (
    workout_id           TEXT NOT NULL,
    user_id              INTEGER NOT NULL REFERENCES users(id),
    whoop_user_id        BIGINT,
    v1_id                BIGINT,
    sport_name           TEXT,
    start_at             TIMESTAMPTZ,
    end_at               TIMESTAMPTZ,
    timezone_offset      TEXT,
    score_state          TEXT,
    strain               NUMERIC,
    average_heart_rate   INTEGER,
    max_heart_rate       INTEGER,
    kilojoule            NUMERIC,
    distance_meter       NUMERIC,
    altitude_gain_meter  NUMERIC,
    raw_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workout_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_whoop_workouts_user_start
    ON whoop_workouts(user_id, start_at DESC);

CREATE TABLE IF NOT EXISTS daily_recovery_observations (
    date                 DATE NOT NULL,
    user_id              INTEGER NOT NULL REFERENCES users(id),
    source               TEXT NOT NULL,
    recovery_score       INTEGER,
    rhr_overnight        INTEGER,
    hrv_overnight_avg    INTEGER,
    sleep_duration_min   INTEGER,
    sleep_deep_min       INTEGER,
    sleep_rem_min        INTEGER,
    sleep_light_min      INTEGER,
    sleep_awake_min      INTEGER,
    sleep_score          INTEGER,
    data_quality         TEXT NOT NULL DEFAULT 'ok',
    spo2_percentage      NUMERIC,
    skin_temp_celsius    NUMERIC,
    strain               NUMERIC,
    avg_hr               NUMERIC,
    max_hr               NUMERIC,
    steps                INTEGER,
    distance_km          NUMERIC,
    active_kcal          INTEGER,
    active_min           NUMERIC,
    raw_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (date, user_id, source)
);

CREATE INDEX IF NOT EXISTS idx_daily_recovery_observations_user_date
    ON daily_recovery_observations(user_id, date DESC);

INSERT INTO daily_recovery_observations
    (date, user_id, source, rhr_overnight, hrv_overnight_avg, sleep_duration_min,
     sleep_score, sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
     steps, distance_km, active_kcal, active_min, data_quality, raw_json, updated_at)
SELECT
    date, user_id, 'garmin_fit_daily', rhr_overnight, hrv_overnight_avg, sleep_duration_min,
    sleep_score, sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
    steps, distance_km, active_kcal, active_min, data_quality,
    jsonb_build_object('source_table', 'recovery_metrics', 'recovery_metrics_source', source),
    now()
FROM (
    SELECT DISTINCT ON (date, user_id) *
    FROM recovery_metrics
    WHERE COALESCE(source, '') <> 'whoop_api_v2'
    ORDER BY date, user_id, (source = 'garmin_fit_daily') DESC, updated_at DESC NULLS LAST, id DESC
) r
ON CONFLICT (date, user_id, source) DO NOTHING;

DROP VIEW IF EXISTS daily_recovery_source_comparison;

CREATE VIEW daily_recovery_source_comparison AS
WITH garmin AS (
    SELECT
        date, user_id, hrv_overnight_avg, rhr_overnight, sleep_duration_min,
        sleep_score, sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
        steps, distance_km, active_kcal, active_min, data_quality
    FROM daily_recovery_observations
    WHERE source = 'garmin_fit_daily'
),
whoop AS (
    SELECT
        date, user_id, recovery_score, hrv_overnight_avg, rhr_overnight, sleep_duration_min,
        sleep_score, sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
        spo2_percentage, skin_temp_celsius, strain, avg_hr, max_hr, data_quality
    FROM daily_recovery_observations
    WHERE source = 'whoop_api_v2'
)
SELECT
    COALESCE(g.date, w.date)       AS date,
    COALESCE(g.user_id, w.user_id) AS user_id,
    g.hrv_overnight_avg            AS garmin_hrv_overnight_avg,
    w.hrv_overnight_avg            AS whoop_hrv_overnight_avg,
    w.hrv_overnight_avg - g.hrv_overnight_avg AS hrv_delta_ms,
    g.rhr_overnight                AS garmin_rhr_overnight,
    w.rhr_overnight                AS whoop_rhr_overnight,
    w.rhr_overnight - g.rhr_overnight AS rhr_delta_bpm,
    g.sleep_duration_min           AS garmin_sleep_duration_min,
    w.sleep_duration_min           AS whoop_sleep_duration_min,
    w.sleep_duration_min - g.sleep_duration_min AS sleep_duration_delta_min,
    g.sleep_score                  AS garmin_sleep_score,
    w.sleep_score                  AS whoop_sleep_score,
    w.sleep_score - g.sleep_score  AS sleep_score_delta,
    w.recovery_score               AS whoop_recovery_score,
    w.strain                       AS whoop_day_strain,
    w.spo2_percentage              AS whoop_spo2_percentage,
    w.skin_temp_celsius            AS whoop_skin_temp_celsius,
    g.steps                        AS garmin_steps,
    g.distance_km                  AS garmin_distance_km,
    g.active_kcal                  AS garmin_active_kcal,
    g.active_min                   AS garmin_active_min,
    g.data_quality                 AS garmin_data_quality,
    w.data_quality                 AS whoop_data_quality,
    CASE
        WHEN g.date IS NULL THEN 'missing_garmin'
        WHEN w.date IS NULL THEN 'missing_whoop'
        WHEN abs(COALESCE(w.hrv_overnight_avg, g.hrv_overnight_avg) - g.hrv_overnight_avg) > 20
          OR abs(COALESCE(w.rhr_overnight, g.rhr_overnight) - g.rhr_overnight) > 8
          OR abs(COALESCE(w.sleep_duration_min, g.sleep_duration_min) - g.sleep_duration_min) > 90
            THEN 'major_delta'
        WHEN abs(COALESCE(w.hrv_overnight_avg, g.hrv_overnight_avg) - g.hrv_overnight_avg) > 10
          OR abs(COALESCE(w.rhr_overnight, g.rhr_overnight) - g.rhr_overnight) > 4
          OR abs(COALESCE(w.sleep_duration_min, g.sleep_duration_min) - g.sleep_duration_min) > 45
            THEN 'minor_delta'
        ELSE 'aligned'
    END AS comparison_status
FROM garmin g
FULL OUTER JOIN whoop w ON w.date = g.date AND w.user_id = g.user_id;

DO $$
BEGIN
    IF to_regrole('roger') IS NOT NULL THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            whoop_sync_runs,
            whoop_recoveries,
            whoop_sleeps,
            whoop_cycles,
            whoop_workouts,
            daily_recovery_observations
        TO roger;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO roger;
    END IF;
    IF to_regrole('drhouse') IS NOT NULL THEN
        GRANT SELECT ON daily_recovery_observations, daily_recovery_source_comparison TO drhouse;
    END IF;
END
$$;

COMMIT;
