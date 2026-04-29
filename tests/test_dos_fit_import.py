import asyncio
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.dos.fit_import import (
    _field_dict_from_frame,
    _generic_field_rows,
    _json_safe,
    _promote_record,
    _promote_session,
)


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


def test_field_dict_from_frame_keeps_values_and_units():
    frame = FakeFrame("record", [FakeField("heart_rate", 142, "bpm")])

    fields, units = _field_dict_from_frame(frame)

    assert fields == {"heart_rate": 142}
    assert units == {"heart_rate": "bpm"}


def test_promote_session_maps_known_fit_fields():
    start = dt.datetime(2026, 4, 27, 10, 30, tzinfo=dt.timezone.utc)
    fields = {
        "sport": "running",
        "sub_sport": "generic",
        "start_time": start,
        "total_elapsed_time": 3600,
        "total_timer_time": 3500,
        "total_distance": 10200,
        "total_calories": 800,
        "avg_heart_rate": 145,
        "max_heart_rate": 171,
        "avg_cadence": 82,
        "avg_power": 230,
        "total_ascent": 120,
        "total_training_effect": 3.1,
        "total_anaerobic_training_effect": 1.2,
    }

    promoted = _promote_session(fields)

    assert promoted["sport"] == "running"
    assert promoted["start_time"] == start
    assert promoted["total_elapsed_time_s"] == 3600
    assert promoted["total_distance_m"] == 10200
    assert promoted["training_effect"] == 3.1
    assert promoted["anaerobic_training_effect"] == 1.2


def test_promote_record_converts_semicircle_positions_to_degrees():
    timestamp = dt.datetime(2026, 4, 27, 10, 31, tzinfo=dt.timezone.utc)
    fields = {
        "timestamp": timestamp,
        "position_lat": 536870912,
        "position_long": 1073741824,
        "distance": 1000,
        "altitude": 250.5,
        "heart_rate": 140,
        "cadence": 80,
        "speed": 3.5,
        "power": 210,
        "temperature": 18,
        "fractional_cadence": 0.5,
    }

    promoted = _promote_record(fields)

    assert promoted["timestamp"] == timestamp
    assert promoted["position_lat"] == pytest.approx(45.0)
    assert promoted["position_long"] == pytest.approx(90.0)
    assert promoted["speed_mps"] == 3.5
    assert promoted["power_w"] == 210


def test_parse_fit_file_collects_sessions_laps_records_and_fields(tmp_path, monkeypatch):
    from agents.dos import fit_import

    fit_path = tmp_path / "activity.fit"
    fit_path.write_bytes(b"fake-fit")

    frames = [
        FakeFrame("file_id", [FakeField("manufacturer", "garmin"), FakeField("product", "fenix")]),
        FakeFrame("session", [FakeField("avg_heart_rate", 145), FakeField("total_distance", 1000)]),
        FakeFrame("lap", [FakeField("total_distance", 500)]),
        FakeFrame(
            "record",
            [
                FakeField("timestamp", dt.datetime(2026, 4, 27, tzinfo=dt.timezone.utc)),
                FakeField("heart_rate", 140),
            ],
        ),
    ]

    class FakeFitReader:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter(frames)

    fake_fitdecode = MagicMock()
    fake_fitdecode.FitReader = FakeFitReader
    fake_fitdecode.FitDataMessage = FakeFrame
    monkeypatch.setattr(fit_import, "fitdecode", fake_fitdecode)

    parsed = fit_import.parse_fit_file(fit_path)

    assert parsed.source_path == fit_path
    assert parsed.file_sha256
    assert parsed.file_id["manufacturer"] == "garmin"
    assert parsed.sessions[0]["avg_heart_rate"] == 145
    assert parsed.laps[0]["lap_index"] == 0
    assert parsed.records[0]["heart_rate"] == 140
    assert any(row["message_name"] == "record" and row["field_name"] == "heart_rate" for row in parsed.fields)


def test_generic_field_rows_preserve_complex_values_as_json_text():
    value_time = dt.datetime(2026, 4, 27, 10, 31, tzinfo=dt.timezone.utc)
    values = {
        "developer_payload": {"zones": [1, 2], "active": True},
        "timestamp": value_time,
        "heart_rate": 140,
        "flag": True,
    }
    units = {"heart_rate": "bpm"}

    rows = _generic_field_rows("record", 0, values, units)
    by_name = {row["field_name"]: row for row in rows}

    assert by_name["developer_payload"]["field_value_text"] == '{"zones": [1, 2], "active": true}'
    assert by_name["timestamp"]["field_value_text"] == '"2026-04-27T10:31:00+00:00"'
    assert by_name["heart_rate"]["field_value_num"] == 140.0
    assert by_name["heart_rate"]["field_value_text"] is None
    assert by_name["flag"]["field_value_text"] == "true"
    assert by_name["flag"]["field_value_num"] is None


def test_parse_fit_file_validates_path_before_dependency(tmp_path, monkeypatch):
    from agents.dos import fit_import

    monkeypatch.setattr(fit_import, "fitdecode", None)

    with pytest.raises(FileNotFoundError):
        fit_import.parse_fit_file(tmp_path / "missing.fit")

    txt_file = tmp_path / "activity.txt"
    txt_file.write_text("not-fit", encoding="utf-8")
    with pytest.raises(ValueError, match=".fit"):
        fit_import.parse_fit_file(txt_file)

    fit_dir = tmp_path / "directory.fit"
    fit_dir.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        fit_import.parse_fit_file(fit_dir)


def test_promoted_raw_json_is_json_safe():
    timestamp = dt.datetime(2026, 4, 27, 10, 31, tzinfo=dt.timezone.utc)
    nested = {"timestamp": timestamp, "values": [1, timestamp], "flag": True}

    safe = _json_safe(nested)
    promoted = _promote_record(nested)

    assert safe == {
        "timestamp": "2026-04-27T10:31:00+00:00",
        "values": [1, "2026-04-27T10:31:00+00:00"],
        "flag": True,
    }
    assert promoted["raw_json"] == safe


@pytest.mark.asyncio
async def test_resolve_activity_id_by_direct_id():
    from agents.dos.fit_import import resolve_activity_id

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 123})

    resolved = await resolve_activity_id(conn, activity_id=123, strava_activity_id=None, user_id=1)

    assert resolved == 123
    conn.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_activity_id_direct_id_wrong_user_raises():
    from agents.dos.fit_import import resolve_activity_id

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="No activity found"):
        await resolve_activity_id(conn, activity_id=123, strava_activity_id=None, user_id=1)


@pytest.mark.asyncio
async def test_resolve_activity_id_by_strava_id():
    from agents.dos.fit_import import resolve_activity_id

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"id": 77})

    resolved = await resolve_activity_id(conn, activity_id=None, strava_activity_id=999, user_id=1)

    assert resolved == 77
    conn.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_activity_id_unknown_strava_id_raises():
    from agents.dos.fit_import import resolve_activity_id

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="No activity found"):
        await resolve_activity_id(conn, activity_id=None, strava_activity_id=999, user_id=1)


@pytest.mark.asyncio
async def test_import_fit_data_skips_duplicate_sha():
    from agents.dos.fit_import import FitActivityData, import_fit_data

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(side_effect=[
        {"id": 123},
        None,
        {"id": 9, "activity_id": 123, "user_id": 1},
    ])
    parsed = FitActivityData(source_path=Path("/tmp/activity.fit"), file_sha256="abc")

    result = await import_fit_data(conn, parsed, activity_id=123, user_id=1)

    assert result["status"] == "already_exists"
    assert result["fit_file_id"] == 9


@pytest.mark.asyncio
async def test_import_fit_data_inserts_sessions_laps_records_and_fields():
    from agents.dos.fit_import import FitActivityData, import_fit_data

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(side_effect=[{"id": 123}, {"id": 44}])
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    timestamp = dt.datetime(2026, 4, 27, 10, 31, tzinfo=dt.timezone.utc)
    parsed = FitActivityData(
        source_path=Path("/tmp/activity.fit"),
        file_sha256="abc",
        file_id={"manufacturer": "garmin", "time_created": timestamp},
        raw_summary={"file_id": {"time_created": timestamp}},
        sessions=[{
            "sport": "running",
            "start_time": timestamp,
            "total_distance_m": 1000,
            "avg_heart_rate": 145,
            "raw_json": {"start_time": timestamp},
        }],
        laps=[{"lap_index": 0, "raw_json": {"start_time": timestamp}}],
        records=[{"timestamp": timestamp, "heart_rate": 140, "raw_json": {"timestamp": timestamp}}],
        fields=[{
            "message_name": "record",
            "message_index": 0,
            "field_name": "heart_rate",
            "field_value_text": None,
            "field_value_num": 140,
            "field_unit": "bpm",
        }],
    )

    result = await import_fit_data(conn, parsed, activity_id=123, user_id=1)

    assert result == {
        "status": "imported",
        "fit_file_id": 44,
        "activity_id": 123,
        "sessions": 1,
        "laps": 1,
        "records": 1,
        "fields": 1,
    }
    assert conn.execute.await_count == 2
    assert conn.executemany.await_count == 2
    conn.transaction.assert_called_once()
    file_insert_args = conn.fetchrow.await_args_list[1].args
    assert '"2026-04-27T10:31:00+00:00"' in file_insert_args[-1]


@pytest.mark.asyncio
async def test_import_fit_data_on_conflict_returns_existing():
    from agents.dos.fit_import import FitActivityData, import_fit_data

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(side_effect=[
        {"id": 123},
        None,
        {"id": 9, "activity_id": 123, "user_id": 1},
    ])
    parsed = FitActivityData(source_path=Path("/tmp/activity.fit"), file_sha256="abc")

    result = await import_fit_data(conn, parsed, activity_id=123, user_id=1)

    assert result["status"] == "already_exists"
    assert result["fit_file_id"] == 9


@pytest.mark.asyncio
async def test_import_fit_data_duplicate_sha_for_different_activity_raises():
    from agents.dos.fit_import import FitActivityData, import_fit_data

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(side_effect=[
        {"id": 456},
        None,
        {"id": 9, "activity_id": 123, "user_id": 1},
    ])
    parsed = FitActivityData(source_path=Path("/tmp/activity.fit"), file_sha256="abc")

    with pytest.raises(ValueError, match="already linked"):
        await import_fit_data(conn, parsed, activity_id=456, user_id=1)


@pytest.mark.asyncio
async def test_import_fit_data_validates_activity_owner_before_insert():
    from agents.dos.fit_import import FitActivityData, import_fit_data

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(return_value=None)
    parsed = FitActivityData(source_path=Path("/tmp/activity.fit"), file_sha256="abc")

    with pytest.raises(ValueError, match="No activity found"):
        await import_fit_data(conn, parsed, activity_id=123, user_id=1)


@pytest.mark.asyncio
async def test_insert_record_batches_chunks_large_inputs():
    from agents.dos.fit_import import _insert_record_batches

    conn = MagicMock()
    conn.executemany = AsyncMock()
    records = [{"heart_rate": i, "raw_json": {"heart_rate": i}} for i in range(5)]

    await _insert_record_batches(conn, fit_file_id=1, activity_id=123, records=records, batch_size=2)

    assert conn.executemany.await_count == 3


def test_garmin_fit_import_tool_is_registered():
    from agents.dos.tools import create_chief_mcp_server

    server = create_chief_mcp_server(Path("/tmp"), redis_a2a=None)
    names = {tool.name for tool in server._tools}

    assert "garmin_fit_import" in names


def test_garmin_fit_import_bad_user_id_returns_mcp_error():
    from agents.dos.tools import create_chief_mcp_server

    server = create_chief_mcp_server(Path("/tmp"), redis_a2a=None)
    tool = next(tool for tool in server._tools if tool.name == "garmin_fit_import")

    result = _run(tool.fn({"file_path": "/tmp/activity.fit", "user_id": "not-an-int"}))

    assert result["is_error"] is True
    assert "FIT import error" in result["content"][0]["text"]


def test_dos_sport_query_documents_fit_tables_and_enriched_view():
    text = Path("src/agents/dos/tools.py").read_text(encoding="utf-8")

    assert "activity_fit_records" in text
    assert "activity_metrics_enriched" in text


def test_coh_tools_document_enriched_fit_view():
    text = Path("src/agents/coh/tools.py").read_text(encoding="utf-8")

    assert "activity_metrics_enriched" in text
    assert "activity_fit_records" in text
