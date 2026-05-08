BEGIN;

CREATE SCHEMA IF NOT EXISTS chro;

CREATE TABLE IF NOT EXISTS chro.flight_activities (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID,
    takeoff_time        TIMESTAMPTZ NOT NULL,
    landing_time        TIMESTAMPTZ,
    takeoff_icao        TEXT,
    landing_icao        TEXT,
    flight_duration     INTEGER,
    flight_type         TEXT,
    experimental        BOOLEAN NOT NULL DEFAULT true,
    aircraft_type       TEXT,
    status              TEXT NOT NULL DEFAULT 'open',
    notes               TEXT,
    source              TEXT NOT NULL DEFAULT 'telegram_coh',
    raw_command         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('open', 'closed', 'cancelled')),
    CHECK (landing_time IS NULL OR landing_time > takeoff_time),
    CHECK (flight_duration IS NULL OR flight_duration > 0)
);

CREATE INDEX IF NOT EXISTS idx_flight_activities_user_takeoff
    ON chro.flight_activities(user_id, takeoff_time DESC);

CREATE INDEX IF NOT EXISTS idx_flight_activities_open
    ON chro.flight_activities(user_id, takeoff_time DESC)
    WHERE status = 'open';

CREATE TABLE IF NOT EXISTS flight_exposures (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         INTEGER NOT NULL,
    flight_user_id  UUID,
    takeoff_at      TIMESTAMPTZ NOT NULL,
    landing_at      TIMESTAMPTZ,
    duration        INTEGER,
    takeoff_icao    TEXT,
    landing_icao    TEXT,
    flight_type     TEXT,
    experimental    BOOLEAN NOT NULL DEFAULT true,
    aircraft_type   TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    source          TEXT NOT NULL DEFAULT 'telegram_coh',
    source_ref      TEXT,
    notes           TEXT,
    raw_context     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('open', 'closed', 'cancelled')),
    CHECK (landing_at IS NULL OR landing_at > takeoff_at),
    CHECK (duration IS NULL OR duration > 0)
);

CREATE INDEX IF NOT EXISTS idx_flight_exposures_user_takeoff
    ON flight_exposures(user_id, takeoff_at DESC);

DROP INDEX IF EXISTS idx_flight_exposures_open;

CREATE UNIQUE INDEX IF NOT EXISTS idx_flight_exposures_open
    ON flight_exposures(user_id)
    WHERE status = 'open';

DO $$
BEGIN
    IF to_regrole('drhouse') IS NOT NULL THEN
        GRANT SELECT, INSERT, UPDATE ON flight_exposures TO drhouse;
    END IF;
    IF to_regrole('roger') IS NOT NULL THEN
        GRANT SELECT ON flight_exposures TO roger;
    END IF;
    IF to_regrole('chro') IS NOT NULL THEN
        GRANT USAGE ON SCHEMA chro TO chro;
        GRANT SELECT, INSERT, UPDATE ON chro.flight_activities TO chro;
    END IF;
END
$$;

COMMIT;
