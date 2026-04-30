BEGIN;

CREATE TABLE IF NOT EXISTS daily_fit_files (
    id                SERIAL PRIMARY KEY,
    date              DATE NOT NULL,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    source_path       TEXT NOT NULL,
    file_sha256       TEXT NOT NULL UNIQUE,
    file_kind         TEXT NOT NULL,
    manufacturer      TEXT,
    product           TEXT,
    serial_number     TEXT,
    time_created      TIMESTAMPTZ,
    imported_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_summary_json  JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_daily_fit_files_date_user
    ON daily_fit_files(date, user_id);

CREATE TABLE IF NOT EXISTS daily_fit_fields (
    id                BIGSERIAL PRIMARY KEY,
    fit_file_id       INTEGER NOT NULL REFERENCES daily_fit_files(id) ON DELETE CASCADE,
    date              DATE NOT NULL,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    message_name      TEXT NOT NULL,
    message_index     INTEGER NOT NULL,
    field_name        TEXT NOT NULL,
    field_value_text  TEXT,
    field_value_num   NUMERIC,
    field_unit        TEXT
);

CREATE INDEX IF NOT EXISTS idx_daily_fit_fields_date_message
    ON daily_fit_fields(date, user_id, message_name, field_name);

CREATE TABLE IF NOT EXISTS daily_wellness_records (
    id               BIGSERIAL PRIMARY KEY,
    fit_file_id      INTEGER NOT NULL REFERENCES daily_fit_files(id) ON DELETE CASCADE,
    date             DATE NOT NULL,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    timestamp        TIMESTAMPTZ,
    heart_rate       INTEGER,
    activity_type    TEXT,
    intensity        NUMERIC,
    active_calories  NUMERIC,
    distance_m       NUMERIC,
    steps            INTEGER,
    duration_min     NUMERIC,
    raw_json         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_daily_wellness_records_time
    ON daily_wellness_records(date, user_id, timestamp);

CREATE TABLE IF NOT EXISTS daily_stress_records (
    id                  BIGSERIAL PRIMARY KEY,
    fit_file_id         INTEGER NOT NULL REFERENCES daily_fit_files(id) ON DELETE CASCADE,
    date                DATE NOT NULL,
    user_id             INTEGER NOT NULL REFERENCES users(id),
    timestamp           TIMESTAMPTZ,
    stress_level_value  INTEGER,
    raw_json            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_daily_stress_records_time
    ON daily_stress_records(date, user_id, timestamp);

CREATE TABLE IF NOT EXISTS daily_respiration_records (
    id                BIGSERIAL PRIMARY KEY,
    fit_file_id       INTEGER NOT NULL REFERENCES daily_fit_files(id) ON DELETE CASCADE,
    date              DATE NOT NULL,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    timestamp         TIMESTAMPTZ,
    respiration_rate  NUMERIC,
    raw_json          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_daily_respiration_records_time
    ON daily_respiration_records(date, user_id, timestamp);

CREATE TABLE IF NOT EXISTS daily_sleep_levels (
    id           BIGSERIAL PRIMARY KEY,
    fit_file_id  INTEGER NOT NULL REFERENCES daily_fit_files(id) ON DELETE CASCADE,
    date         DATE NOT NULL,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    timestamp    TIMESTAMPTZ,
    sleep_level  TEXT,
    raw_json     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_daily_sleep_levels_time
    ON daily_sleep_levels(date, user_id, timestamp);

CREATE TABLE IF NOT EXISTS daily_hrv_values (
    id           BIGSERIAL PRIMARY KEY,
    fit_file_id  INTEGER NOT NULL REFERENCES daily_fit_files(id) ON DELETE CASCADE,
    date         DATE NOT NULL,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    timestamp    TIMESTAMPTZ,
    value_ms     NUMERIC,
    raw_json     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_daily_hrv_values_time
    ON daily_hrv_values(date, user_id, timestamp);

CREATE TABLE IF NOT EXISTS daily_skin_temp_overnight (
    id                         BIGSERIAL PRIMARY KEY,
    fit_file_id                INTEGER NOT NULL REFERENCES daily_fit_files(id) ON DELETE CASCADE,
    date                       DATE NOT NULL,
    user_id                    INTEGER NOT NULL REFERENCES users(id),
    average_deviation_c        NUMERIC,
    average_7_day_deviation_c  NUMERIC,
    nightly_value_c            NUMERIC,
    raw_json                   JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_daily_skin_temp_date
    ON daily_skin_temp_overnight(date, user_id);

CREATE OR REPLACE VIEW daily_fitness_enriched AS
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
        max(steps) AS latest_steps,
        max(active_calories) AS latest_active_calories,
        max(distance_m) AS latest_distance_m
    FROM daily_wellness_records
    GROUP BY date, user_id
),
skin AS (
    SELECT DISTINCT ON (date, user_id)
        date,
        user_id,
        average_deviation_c AS skin_average_deviation_c,
        average_7_day_deviation_c AS skin_average_7_day_deviation_c,
        nightly_value_c AS skin_nightly_value_c
    FROM daily_skin_temp_overnight
    ORDER BY date, user_id, id DESC
)
SELECT
    COALESCE(r.date, f.date) AS date,
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
    w.min_wellness_hr,
    w.avg_wellness_hr,
    w.latest_steps,
    w.latest_active_calories,
    w.latest_distance_m,
    s.skin_average_deviation_c,
    s.skin_average_7_day_deviation_c,
    s.skin_nightly_value_c
FROM recovery_metrics r
FULL OUTER JOIN files f ON f.date = r.date AND f.user_id = r.user_id
LEFT JOIN wellness w ON w.date = COALESCE(r.date, f.date) AND w.user_id = COALESCE(r.user_id, f.user_id)
LEFT JOIN skin s ON s.date = COALESCE(r.date, f.date) AND s.user_id = COALESCE(r.user_id, f.user_id);

DO $$
BEGIN
    IF to_regrole('drhouse') IS NOT NULL THEN
        GRANT SELECT ON daily_fit_files, daily_fit_fields, daily_wellness_records,
            daily_stress_records, daily_respiration_records, daily_sleep_levels,
            daily_hrv_values, daily_skin_temp_overnight, daily_fitness_enriched TO drhouse;
    END IF;
END
$$;

COMMIT;
