from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "007_daily_fitness_fit.sql"
ACTIVITY_MIGRATION = ROOT / "migrations" / "008_recovery_metrics_activity.sql"


def test_daily_fitness_migration_creates_raw_tables_and_enriched_view():
    sql = MIGRATION.read_text(encoding="utf-8")

    for name in (
        "daily_fit_files",
        "daily_fit_fields",
        "daily_wellness_records",
        "daily_stress_records",
        "daily_respiration_records",
        "daily_sleep_levels",
        "daily_hrv_values",
        "daily_skin_temp_overnight",
        "daily_fitness_enriched",
    ):
        assert name in sql

    assert "file_sha256" in sql
    assert "UNIQUE" in sql
    assert "REFERENCES users(id)" in sql
    assert "REFERENCES daily_fit_files(id)" in sql
    assert "INSERT" not in sql
    assert "CREATE OR REPLACE VIEW daily_fitness_enriched" in sql
    assert "recovery_metrics" in sql
    assert "to_regrole('drhouse')" in sql


def test_recovery_metrics_activity_migration_adds_daily_activity_rollups():
    sql = ACTIVITY_MIGRATION.read_text(encoding="utf-8")

    for name in (
        "steps",
        "distance_km",
        "active_kcal",
        "active_min",
        "data_quality",
        "daily_fitness_enriched",
    ):
        assert name in sql

    assert "ALTER TABLE recovery_metrics" in sql
    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "COALESCE(r.steps" in sql
    assert "latest_active_min" in sql
    assert "to_regrole('drhouse')" in sql
