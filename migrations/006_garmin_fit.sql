BEGIN;

CREATE TABLE IF NOT EXISTS activity_fit_files (
    id                 SERIAL PRIMARY KEY,
    activity_id        INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_id            INTEGER NOT NULL REFERENCES users(id),
    source_path        TEXT NOT NULL,
    file_sha256        TEXT NOT NULL UNIQUE,
    manufacturer       TEXT,
    product            TEXT,
    serial_number      TEXT,
    time_created       TIMESTAMPTZ,
    imported_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_summary_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT activity_fit_files_id_activity_id_key UNIQUE (id, activity_id)
);

CREATE INDEX IF NOT EXISTS idx_activity_fit_files_activity
    ON activity_fit_files(activity_id);

CREATE TABLE IF NOT EXISTS activity_fit_sessions (
    id                         SERIAL PRIMARY KEY,
    fit_file_id                INTEGER NOT NULL,
    activity_id                INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    sport                      TEXT,
    sub_sport                  TEXT,
    start_time                 TIMESTAMPTZ,
    total_elapsed_time_s       NUMERIC,
    total_timer_time_s         NUMERIC,
    total_distance_m           NUMERIC,
    total_calories             INTEGER,
    avg_heart_rate             INTEGER,
    max_heart_rate             INTEGER,
    avg_cadence                NUMERIC,
    max_cadence                NUMERIC,
    avg_power                  NUMERIC,
    max_power                  NUMERIC,
    total_ascent_m             NUMERIC,
    training_effect            NUMERIC,
    anaerobic_training_effect  NUMERIC,
    raw_json                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT activity_fit_sessions_file_activity_fkey FOREIGN KEY (fit_file_id, activity_id)
        REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_activity_fit_sessions_activity
    ON activity_fit_sessions(activity_id);

CREATE INDEX IF NOT EXISTS idx_activity_fit_sessions_file_activity
    ON activity_fit_sessions(fit_file_id, activity_id);

CREATE TABLE IF NOT EXISTS activity_fit_laps (
    id                    SERIAL PRIMARY KEY,
    fit_file_id           INTEGER NOT NULL,
    activity_id           INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    lap_index             INTEGER NOT NULL,
    start_time            TIMESTAMPTZ,
    total_elapsed_time_s  NUMERIC,
    total_timer_time_s    NUMERIC,
    total_distance_m      NUMERIC,
    total_calories        INTEGER,
    avg_heart_rate        INTEGER,
    max_heart_rate        INTEGER,
    avg_cadence           NUMERIC,
    max_cadence           NUMERIC,
    avg_power             NUMERIC,
    max_power             NUMERIC,
    raw_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT activity_fit_laps_file_activity_fkey FOREIGN KEY (fit_file_id, activity_id)
        REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_activity_fit_laps_activity
    ON activity_fit_laps(activity_id, lap_index);

CREATE INDEX IF NOT EXISTS idx_activity_fit_laps_file_activity
    ON activity_fit_laps(fit_file_id, activity_id);

CREATE TABLE IF NOT EXISTS activity_fit_records (
    id                  BIGSERIAL PRIMARY KEY,
    fit_file_id         INTEGER NOT NULL,
    activity_id         INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    timestamp           TIMESTAMPTZ,
    position_lat        DOUBLE PRECISION,
    position_long       DOUBLE PRECISION,
    distance_m          NUMERIC,
    altitude_m          NUMERIC,
    heart_rate          INTEGER,
    cadence             NUMERIC,
    speed_mps           NUMERIC,
    power_w             NUMERIC,
    temperature_c       NUMERIC,
    fractional_cadence  NUMERIC,
    raw_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT activity_fit_records_file_activity_fkey FOREIGN KEY (fit_file_id, activity_id)
        REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_activity_fit_records_activity_time
    ON activity_fit_records(activity_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_activity_fit_records_file_activity
    ON activity_fit_records(fit_file_id, activity_id);

CREATE TABLE IF NOT EXISTS activity_fit_fields (
    id                BIGSERIAL PRIMARY KEY,
    fit_file_id       INTEGER NOT NULL,
    activity_id       INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    message_name      TEXT NOT NULL,
    message_index     INTEGER NOT NULL,
    field_name        TEXT NOT NULL,
    field_value_text  TEXT,
    field_value_num   NUMERIC,
    field_unit        TEXT,
    CONSTRAINT activity_fit_fields_file_activity_fkey FOREIGN KEY (fit_file_id, activity_id)
        REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_activity_fit_fields_activity_message
    ON activity_fit_fields(activity_id, message_name, field_name);

CREATE INDEX IF NOT EXISTS idx_activity_fit_fields_file_activity
    ON activity_fit_fields(fit_file_id, activity_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'activity_fit_files_id_activity_id_key'
    ) THEN
        ALTER TABLE activity_fit_files
            ADD CONSTRAINT activity_fit_files_id_activity_id_key UNIQUE (id, activity_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'activity_fit_sessions_file_activity_fkey'
    ) THEN
        ALTER TABLE activity_fit_sessions
            ADD CONSTRAINT activity_fit_sessions_file_activity_fkey
            FOREIGN KEY (fit_file_id, activity_id)
            REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'activity_fit_laps_file_activity_fkey'
    ) THEN
        ALTER TABLE activity_fit_laps
            ADD CONSTRAINT activity_fit_laps_file_activity_fkey
            FOREIGN KEY (fit_file_id, activity_id)
            REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'activity_fit_records_file_activity_fkey'
    ) THEN
        ALTER TABLE activity_fit_records
            ADD CONSTRAINT activity_fit_records_file_activity_fkey
            FOREIGN KEY (fit_file_id, activity_id)
            REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'activity_fit_fields_file_activity_fkey'
    ) THEN
        ALTER TABLE activity_fit_fields
            ADD CONSTRAINT activity_fit_fields_file_activity_fkey
            FOREIGN KEY (fit_file_id, activity_id)
            REFERENCES activity_fit_files(id, activity_id) ON DELETE CASCADE;
    END IF;
END
$$;

CREATE OR REPLACE VIEW activity_metrics_enriched AS
WITH latest_fit AS (
    SELECT DISTINCT ON (activity_id)
        id AS fit_file_id,
        activity_id,
        imported_at
    FROM activity_fit_files
    ORDER BY activity_id, imported_at DESC, id DESC
),
fit_session AS (
    SELECT DISTINCT ON (s.activity_id)
        s.*
    FROM activity_fit_sessions s
    JOIN latest_fit lf ON lf.fit_file_id = s.fit_file_id AND lf.activity_id = s.activity_id
    ORDER BY s.activity_id, s.total_timer_time_s DESC NULLS LAST, s.start_time NULLS LAST, s.id DESC
)
SELECT
    a.id AS activity_id,
    a.user_id,
    a.source,
    a.type,
    a.date,
    a.strava_activity_id,
    a.notes,
    a.raw_json AS strava_raw_json,
    lf.fit_file_id,
    lf.imported_at AS fit_imported_at,
    a.duration_min AS strava_duration_min,
    (fs.total_timer_time_s / 60.0)::numeric AS fit_duration_min,
    COALESCE((fs.total_timer_time_s / 60.0)::numeric, a.duration_min) AS canonical_duration_min,
    a.distance_km AS strava_distance_km,
    (fs.total_distance_m / 1000.0)::numeric AS fit_distance_km,
    COALESCE((fs.total_distance_m / 1000.0)::numeric, a.distance_km) AS canonical_distance_km,
    a.avg_hr AS strava_avg_hr,
    fs.avg_heart_rate::numeric AS fit_avg_hr,
    COALESCE(fs.avg_heart_rate::numeric, a.avg_hr) AS canonical_avg_hr,
    a.max_hr AS strava_max_hr,
    fs.max_heart_rate::numeric AS fit_max_hr,
    COALESCE(fs.max_heart_rate::numeric, a.max_hr) AS canonical_max_hr,
    a.calories AS strava_calories,
    fs.total_calories AS fit_calories,
    COALESCE(fs.total_calories, a.calories) AS canonical_calories,
    a.avg_cadence AS strava_avg_cadence,
    fs.avg_cadence AS fit_avg_cadence,
    COALESCE(fs.avg_cadence, a.avg_cadence) AS canonical_avg_cadence,
    a.elevation_gain_m AS strava_elevation_gain_m,
    fs.total_ascent_m AS fit_elevation_gain_m,
    COALESCE(fs.total_ascent_m, a.elevation_gain_m) AS canonical_elevation_gain_m,
    fs.avg_power AS canonical_avg_power,
    fs.max_power AS canonical_max_power,
    fs.training_effect AS canonical_training_effect,
    fs.anaerobic_training_effect AS canonical_anaerobic_training_effect,
    a.suffer_score AS strava_suffer_score,
    a.load_score AS strava_load_score
FROM activities a
LEFT JOIN latest_fit lf ON lf.activity_id = a.id
LEFT JOIN fit_session fs ON fs.activity_id = a.id;

DO $$
BEGIN
    IF to_regrole('drhouse') IS NOT NULL THEN
        GRANT SELECT ON activity_fit_files, activity_fit_sessions, activity_fit_laps,
            activity_fit_records, activity_fit_fields, activity_metrics_enriched TO drhouse;
    END IF;
END
$$;

COMMIT;
