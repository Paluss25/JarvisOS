"""Tests for COH health DB schema compatibility."""

from pathlib import Path

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
