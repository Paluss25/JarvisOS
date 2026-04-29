import asyncio
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class FakeField:
    def __init__(self, name, value, units=None):
        self.name = name
        self.value = value
        self.units = units


class FakeFrame:
    def __init__(self, name, fields):
        self.name = name
        self.fields = fields


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_parse_daily_fitness_folder_promotes_wellness_sleep_hrv_and_skin_temp(tmp_path, monkeypatch):
    from agents.dos import daily_fitness_import

    folder = tmp_path / "2026-04-27_fitness"
    folder.mkdir()
    wellness = folder / "1_WELLNESS.fit"
    hrv = folder / "2_HRV_STATUS.fit"
    sleep = folder / "3_SLEEP_DATA.fit"
    skin = folder / "4_SKIN_TEMP.fit"
    for path in (wellness, hrv, sleep, skin):
        path.write_bytes(b"fake-fit")

    start = dt.datetime(2026, 4, 26, 22, 0, tzinfo=dt.timezone.utc)
    frames_by_path = {
        str(wellness): [
            FakeFrame("file_id", [FakeField("manufacturer", "garmin"), FakeField("serial_number", 3447005442)]),
            FakeFrame("monitoring", [FakeField("timestamp", start), FakeField("heart_rate", 57), FakeField("steps", 100)]),
            FakeFrame("stress_level", [FakeField("stress_level_time", start), FakeField("stress_level_value", 16)]),
            FakeFrame("respiration_rate", [FakeField("timestamp", start), FakeField("respiration_rate", 14.25)]),
        ],
        str(hrv): [
            FakeFrame("file_id", [FakeField("manufacturer", "garmin")]),
            FakeFrame("hrv_value", [FakeField("timestamp", start), FakeField("value", 41.0)]),
            FakeFrame("hrv_value", [FakeField("timestamp", start + dt.timedelta(minutes=5)), FakeField("value", 61.0)]),
        ],
        str(sleep): [
            FakeFrame("sleep_level", [FakeField("timestamp", start), FakeField("sleep_level", "light")]),
            FakeFrame("sleep_level", [FakeField("timestamp", start + dt.timedelta(minutes=30)), FakeField("sleep_level", "deep")]),
            FakeFrame("sleep_level", [FakeField("timestamp", start + dt.timedelta(minutes=60)), FakeField("sleep_level", "awake")]),
        ],
        str(skin): [
            FakeFrame(
                "skin_temp_overnight",
                [
                    FakeField("average_deviation", -0.2),
                    FakeField("average_7_day_deviation", -0.1),
                    FakeField("nightly_value", 36.3),
                ],
            ),
        ],
    }

    class FakeFitReader:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter(frames_by_path[self.path])

    fake_fitdecode = MagicMock()
    fake_fitdecode.FitReader = FakeFitReader
    fake_fitdecode.FitDataMessage = FakeFrame
    monkeypatch.setattr(daily_fitness_import, "fitdecode", fake_fitdecode)

    parsed = daily_fitness_import.parse_daily_fitness_folder(folder, date=dt.date(2026, 4, 27))

    assert len(parsed.files) == 4
    assert parsed.files[0]["file_kind"] == "WELLNESS"
    assert parsed.wellness_records[0]["heart_rate"] == 57
    assert parsed.stress_records[0]["stress_level_value"] == 16
    assert parsed.respiration_records[0]["respiration_rate"] == 14.25
    assert [row["sleep_level"] for row in parsed.sleep_levels] == ["light", "deep", "awake"]
    assert parsed.hrv_values[1]["value_ms"] == 61.0
    assert parsed.skin_temp_overnight[0]["nightly_value_c"] == 36.3
    assert parsed.recovery_summary["hrv_overnight_avg"] == 51
    assert parsed.recovery_summary["stress_avg"] == 16
    assert parsed.recovery_summary["sleep_light_min"] == 30
    assert parsed.recovery_summary["sleep_deep_min"] == 30


@pytest.mark.asyncio
async def test_import_daily_fitness_data_inserts_files_raw_rows_and_recovery_summary():
    from agents.dos.daily_fitness_import import DailyFitnessData, import_daily_fitness_data

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(side_effect=[{"id": 10}, {"id": 11}])
    conn.executemany = AsyncMock()
    conn.execute = AsyncMock()
    date = dt.date(2026, 4, 27)
    timestamp = dt.datetime(2026, 4, 27, 5, 31, tzinfo=dt.timezone.utc)
    parsed = DailyFitnessData(
        date=date,
        source_folder=Path("/tmp/2026-04-27_fitness"),
        files=[
            {
                "source_path": Path("/tmp/2026-04-27_fitness/1_WELLNESS.fit"),
                "file_sha256": "sha1",
                "file_kind": "WELLNESS",
                "file_id": {"serial_number": 3447005442},
                "raw_summary": {"counts": {"fields": 2}},
            },
            {
                "source_path": Path("/tmp/2026-04-27_fitness/2_HRV_STATUS.fit"),
                "file_sha256": "sha2",
                "file_kind": "HRV_STATUS",
                "file_id": {},
                "raw_summary": {"counts": {"fields": 1}},
            },
        ],
        fields=[
            {"file_sha256": "sha1", "message_name": "monitoring", "message_index": 0, "field_name": "heart_rate", "field_value_text": None, "field_value_num": 57, "field_unit": "bpm"},
            {"file_sha256": "sha2", "message_name": "hrv_value", "message_index": 0, "field_name": "value", "field_value_text": None, "field_value_num": 51, "field_unit": "ms"},
        ],
        wellness_records=[{"file_sha256": "sha1", "timestamp": timestamp, "heart_rate": 57, "steps": 100, "raw_json": {"timestamp": timestamp}}],
        hrv_values=[{"file_sha256": "sha2", "timestamp": timestamp, "value_ms": 51.0, "raw_json": {"timestamp": timestamp}}],
        recovery_summary={"hrv_overnight_avg": 51, "rhr_overnight": 57},
    )

    result = await import_daily_fitness_data(conn, parsed, user_id=1)

    assert result["status"] == "imported"
    assert result["files_imported"] == 2
    assert result["fields"] == 2
    assert result["recovery_metrics_upserted"] is True
    assert conn.transaction.called
    assert conn.executemany.await_count >= 3
    upsert_sql = conn.execute.await_args.args[0]
    assert "INSERT INTO recovery_metrics" in upsert_sql


@pytest.mark.asyncio
async def test_import_daily_fitness_data_skips_existing_file_sha_but_upserts_recovery():
    from agents.dos.daily_fitness_import import DailyFitnessData, import_daily_fitness_data

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(side_effect=[None, {"id": 9, "date": dt.date(2026, 4, 27), "user_id": 1}])
    conn.executemany = AsyncMock()
    conn.execute = AsyncMock()
    parsed = DailyFitnessData(
        date=dt.date(2026, 4, 27),
        source_folder=Path("/tmp/2026-04-27_fitness"),
        files=[{
            "source_path": Path("/tmp/2026-04-27_fitness/1_WELLNESS.fit"),
            "file_sha256": "sha1",
            "file_kind": "WELLNESS",
            "file_id": {},
            "raw_summary": {},
        }],
        recovery_summary={"stress_avg": 16},
    )

    result = await import_daily_fitness_data(conn, parsed, user_id=1)

    assert result["status"] == "imported"
    assert result["files_imported"] == 0
    assert result["files_existing"] == 1
    conn.execute.assert_awaited_once()


def test_garmin_fitness_import_tool_is_registered():
    from agents.dos.tools import create_chief_mcp_server

    server = create_chief_mcp_server(Path("/tmp"), redis_a2a=None)
    names = {tool.name for tool in server._tools}

    assert "garmin_fitness_import" in names


def test_garmin_fitness_import_bad_user_id_returns_mcp_error():
    from agents.dos.tools import create_chief_mcp_server

    server = create_chief_mcp_server(Path("/tmp"), redis_a2a=None)
    tool = next(tool for tool in server._tools if tool.name == "garmin_fitness_import")

    result = _run(tool.fn({"folder_path": "/tmp/2026-04-27_fitness", "date": "2026-04-27", "user_id": "nope"}))

    assert result["is_error"] is True
    assert "Fitness import error" in result["content"][0]["text"]


def test_dos_and_coh_document_daily_fitness_tables_and_view():
    from agents.coh.tools import create_drhouse_mcp_server
    from agents.dos.tools import create_chief_mcp_server

    dos_server = create_chief_mcp_server(Path("/tmp"), redis_a2a=None)
    sport_query = next(tool for tool in dos_server._tools if tool.name == "sport_query")
    assert "daily_fit_files" in sport_query.description
    assert "daily_fitness_enriched" in sport_query.description

    coh_server = create_drhouse_mcp_server(Path("/tmp"), redis_a2a=None)
    health_query = next(tool for tool in coh_server._tools if tool.name == "health_query")
    assert "daily_fit_files" in health_query.description
    assert "daily_fitness_enriched" in health_query.description
