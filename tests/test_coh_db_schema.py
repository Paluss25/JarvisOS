"""Tests for COH health DB schema compatibility."""

import pytest

from agents.coh import db
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
