from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "006_garmin_fit.sql"


def test_garmin_fit_migration_creates_core_tables_and_view():
    sql = MIGRATION.read_text(encoding="utf-8")

    for name in (
        "activity_fit_files",
        "activity_fit_sessions",
        "activity_fit_laps",
        "activity_fit_records",
        "activity_fit_fields",
        "activity_metrics_enriched",
    ):
        assert name in sql

    assert "UNIQUE" in sql
    assert "file_sha256" in sql
    assert "REFERENCES activities(id)" in sql
    assert "UNIQUE (id, activity_id)" in sql
    assert "FOREIGN KEY (fit_file_id, activity_id)" in sql
    assert "activity_fit_files_id_activity_id_key" in sql
    assert "idx_activity_fit_records_file_activity" in sql
    assert "CREATE OR REPLACE VIEW activity_metrics_enriched" in sql
    assert "JOIN latest_fit lf ON lf.fit_file_id = s.fit_file_id AND lf.activity_id = s.activity_id" in sql
    assert "s.total_timer_time_s DESC NULLS LAST" in sql
    assert "COALESCE(fs.avg_heart_rate::numeric, a.avg_hr)" in sql
    assert "to_regrole('drhouse')" in sql
