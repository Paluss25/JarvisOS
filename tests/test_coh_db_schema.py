"""Tests for COH health DB schema compatibility."""

from pathlib import Path

import pytest

from agents.coh import db
from agents.coh.config import DRHOUSE_BUILTIN_CRONS, build_drhouse_config
from agents.coh.tools import create_drhouse_mcp_server


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


class _CaptureConn:
    def __init__(self):
        self.sql = []
        self.args = []

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        self.args.append(args)
        return []


def _cron(name: str) -> dict:
    for cron in DRHOUSE_BUILTIN_CRONS:
        if cron["name"] == name:
            return cron
    raise AssertionError(f"{name} cron not found")


@pytest.mark.asyncio
async def test_lab_anomalies_queries_health_public_tables(monkeypatch):
    conn = _CaptureConn()

    async def fake_pool():
        return _FakePool(conn)

    monkeypatch.setattr(db, "pool", fake_pool)

    await db.fetch_lab_anomalies("paluss", 90)

    query = conn.sql[0]
    assert "FROM public.lab_values v" in query
    assert "JOIN public.lab_panels p" in query
    assert "coh." not in query
    assert "p.panel_name" in query
    assert "panel_type" not in query
    assert conn.args[0][0] != "paluss"


@pytest.mark.asyncio
async def test_lab_values_queries_health_public_tables(monkeypatch):
    conn = _CaptureConn()

    async def fake_pool():
        return _FakePool(conn)

    monkeypatch.setattr(db, "pool", fake_pool)

    await db.fetch_lab_values("LDL", "paluss")

    query = conn.sql[0]
    assert "FROM public.lab_values v" in query
    assert "JOIN public.lab_panels p" in query
    assert "coh." not in query
    assert conn.args[0][0] != "paluss"


def test_medical_user_alias_maps_paluss_to_health_uuid():
    assert db.resolve_medical_user_id("paluss") == db.DEFAULT_MEDICAL_USER_ID
    assert db.resolve_medical_user_id("me") == db.DEFAULT_MEDICAL_USER_ID
    assert db.resolve_medical_user_id("75f9a1ac-e4ca-41cd-8d2b-1f393db7e732") == (
        "75f9a1ac-e4ca-41cd-8d2b-1f393db7e732"
    )


def test_coh_image_caption_routes_recovery_photos_to_dos_whoop_sync():
    caption = build_drhouse_config().default_image_caption

    assert "Garmin recovery/sleep/HRV/stress/body battery" in caption
    assert "send_message(to='dos'" in caption
    assert "whoop_sync" in caption
    assert "date_from" in caption
    assert "date_to" in caption
    assert "mode='async'" in caption


def test_coh_eod_consolidation_checks_whoop_after_late_photos():
    prompt = _cron("eod_health_consolidation")["prompt"]

    assert "late Garmin recovery photos" in prompt
    assert "send_message(to='dos'" in prompt
    assert "whoop_sync" in prompt
    assert "daily_recovery_source_comparison" in prompt


def test_health_tool_describes_lab_public_schema(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)

    health_query = next(tool for tool in server._tools if tool.name == "health_query")
    lab_query = next(tool for tool in server._tools if tool.name == "lab_query")
    combined = f"{health_query.description}\n{lab_query.description}"

    assert "lab_panels" in combined
    assert "lab_values" in combined
    assert "panel_name" in combined
    assert "panel_type does not exist" in combined
    assert "coh.lab" not in combined


@pytest.mark.asyncio
async def test_lab_query_uses_contains_match_for_short_parameter_names(monkeypatch, tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    lab_query = next(tool for tool in server._tools if tool.name == "lab_query")
    captured = {}

    class _Resp:
        is_success = True

        def json(self):
            return []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            captured["params"] = params
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    await lab_query.fn({"parameter_name": "HDL"})

    assert captured["params"]["parameter_name"] == "%HDL%"


def test_health_tool_describes_whoop_schema(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)

    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    assert "whoop_workouts" in health_query.description
    assert "workout_id" in health_query.description
    assert "id does not exist" in health_query.description
    assert "whoop_sync_runs" in health_query.description
    assert "items_synced does not exist" in health_query.description


@pytest.mark.asyncio
async def test_health_query_preflights_sleep_total_min_alias(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    result = await health_query.fn({
        "database": "sport",
        "query": "SELECT date, sleep_total_min FROM daily_fitness_enriched ORDER BY date DESC LIMIT 1",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'sleep_total_min' → 'sleep_duration_min'" in text
    assert "daily_fitness_enriched" in text


@pytest.mark.asyncio
async def test_health_query_preflights_daily_fitness_recovery_score(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    result = await health_query.fn({
        "database": "sport",
        "query": "SELECT date, source, sleep_duration_min, recovery_score FROM daily_fitness_enriched ORDER BY date DESC LIMIT 1",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'recovery_score' on table 'daily_fitness_enriched' → use 'daily_recovery_observations' or 'daily_recovery_source_comparison'" in text


@pytest.mark.asyncio
async def test_health_query_preflights_whoop_workout_id_alias(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    result = await health_query.fn({
        "database": "sport",
        "query": "SELECT id, start_at, end_at, sport_name FROM whoop_workouts ORDER BY start_at DESC LIMIT 1",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'id' on table 'whoop_workouts' → use 'workout_id'" in text
    assert "whoop_workouts" in text


@pytest.mark.asyncio
async def test_health_query_preflights_whoop_sync_run_columns(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    result = await health_query.fn({
        "database": "sport",
        "query": "SELECT started_at, status, source, items_synced FROM whoop_sync_runs ORDER BY started_at DESC LIMIT 1",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'source' on table 'whoop_sync_runs' → column does not exist" in text
    assert "'items_synced' on table 'whoop_sync_runs' → use recoveries_seen, sleeps_seen, cycles_seen, workouts_seen" in text


@pytest.mark.asyncio
async def test_health_query_preflights_whoop_sync_finished_at(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    result = await health_query.fn({
        "database": "sport",
        "query": "SELECT id, status, started_at, finished_at, date_from, date_to FROM whoop_sync_runs ORDER BY started_at DESC LIMIT 1",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'finished_at' on table 'whoop_sync_runs' → use 'completed_at'" in text


@pytest.mark.asyncio
async def test_health_query_preflights_activities_event_columns(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    result = await health_query.fn({
        "database": "sport",
        "query": "SELECT id, source, type, name, start_time, duration_min FROM activities ORDER BY start_time DESC LIMIT 5",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'name' on table 'activities' → column does not exist" in text
    assert "'start_time' on table 'activities' → use 'date'" in text


@pytest.mark.asyncio
async def test_health_query_preflights_whoop_start_time_alias(tmp_path):
    server = create_drhouse_mcp_server(tmp_path)
    health_query = next(tool for tool in server._tools if tool.name == "health_query")

    result = await health_query.fn({
        "database": "sport",
        "query": "SELECT workout_id, sport_name, start_time FROM whoop_workouts ORDER BY start_time DESC LIMIT 5",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'start_time' on table 'whoop_workouts' → use 'start_at'" in text


def test_health_query_prompt_mentions_flight_exposures():
    server = create_drhouse_mcp_server(Path("/tmp/coh"))
    health_tool = next(entry for entry in server._tools if entry.name == "health_query")

    assert "flight_exposures" in health_tool.description
    assert "takeoff_at" in health_tool.description
    assert "landing_at" in health_tool.description
    assert "daily_recovery_observations" in health_tool.description
    assert "whoop_api_v2" in health_tool.description
    assert "FLIGHT_USER_ID" in health_tool.description
    assert "SPORT_USER_ID" in health_tool.description
