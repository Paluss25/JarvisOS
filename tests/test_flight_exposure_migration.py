from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "012_flight_exposure.sql"


def test_flight_exposure_migration_creates_chro_and_sport_tables():
    sql = MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(sql.split())

    assert "CREATE TABLE IF NOT EXISTS chro.flight_activities" in sql
    assert "CREATE TABLE IF NOT EXISTS flight_exposures" in sql

    assert "id UUID PRIMARY KEY DEFAULT gen_random_uuid()" in normalized
    assert "user_id UUID" in normalized
    assert "takeoff_time TIMESTAMPTZ NOT NULL" in normalized
    assert "landing_time TIMESTAMPTZ" in normalized
    assert "takeoff_icao TEXT" in normalized
    assert "landing_icao TEXT" in normalized
    assert "flight_duration INTEGER" in normalized
    assert "flight_type TEXT" in normalized
    assert "experimental BOOLEAN NOT NULL DEFAULT true" in normalized
    assert "aircraft_type TEXT" in normalized
    assert "status TEXT NOT NULL DEFAULT 'open'" in normalized
    assert "source TEXT NOT NULL DEFAULT 'telegram_coh'" in normalized
    assert "raw_command TEXT" in normalized
    assert "created_at TIMESTAMPTZ NOT NULL DEFAULT now()" in normalized
    assert "updated_at TIMESTAMPTZ NOT NULL DEFAULT now()" in normalized
    assert "CHECK (status IN ('open', 'closed', 'cancelled'))" in normalized
    assert "CHECK (landing_time IS NULL OR landing_time > takeoff_time)" in normalized
    assert "CHECK (flight_duration IS NULL OR flight_duration > 0)" in normalized

    assert "user_id INTEGER NOT NULL" in normalized
    assert "flight_user_id UUID" in normalized
    assert "takeoff_at TIMESTAMPTZ NOT NULL" in normalized
    assert "landing_at TIMESTAMPTZ" in normalized
    assert "duration INTEGER" in normalized
    assert "source_ref TEXT" in normalized
    assert "raw_context JSONB NOT NULL DEFAULT '{}'::jsonb" in normalized
    assert "CHECK (landing_at IS NULL OR landing_at > takeoff_at)" in normalized
    assert "CHECK (duration IS NULL OR duration > 0)" in normalized


def test_flight_exposure_migration_creates_expected_indexes():
    sql = MIGRATION.read_text(encoding="utf-8")
    normalized = " ".join(sql.split())

    assert "CREATE INDEX IF NOT EXISTS idx_flight_activities_user_takeoff ON chro.flight_activities(user_id, takeoff_time DESC)" in normalized
    assert "CREATE INDEX IF NOT EXISTS idx_flight_activities_open ON chro.flight_activities(user_id, takeoff_time DESC) WHERE status = 'open'" in normalized
    assert "CREATE INDEX IF NOT EXISTS idx_flight_exposures_user_takeoff ON flight_exposures(user_id, takeoff_at DESC)" in normalized
    assert "DROP INDEX IF EXISTS idx_flight_exposures_open" in normalized
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_flight_exposures_open ON flight_exposures(user_id) WHERE status = 'open'" in normalized


def test_flight_exposure_migration_has_no_cross_database_foreign_keys():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "references chro.flight_activities" not in sql
    assert "references flight_exposures" not in sql
    assert "references users(id)" not in sql


def test_flight_exposure_migration_grants_expected_roles():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "IF to_regrole('drhouse') IS NOT NULL" in sql
    assert "IF to_regrole('roger') IS NOT NULL" in sql
    assert "IF to_regrole('chro') IS NOT NULL" in sql
    assert "GRANT USAGE ON SCHEMA chro TO chro" in sql
    assert "TO drhouse" in sql
    assert "TO roger" in sql
    assert "TO chro" in sql
