"""Tests for CHRO human_res schema compatibility."""

from pathlib import Path
import sys
import types
import uuid

import pytest

from agents.chro import db
from agents.chro.config import CHRO_BUILTIN_CRONS
from agents.chro.tools import _normalize_chro_sql


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
    for cron in CHRO_BUILTIN_CRONS:
        if cron["name"] == name:
            return cron
    raise AssertionError(f"{name} cron not found")


@pytest.mark.asyncio
async def test_recent_payslips_maps_paluss_to_hr_uuid(monkeypatch):
    conn = _CaptureConn()

    async def fake_pool():
        return _FakePool(conn)

    monkeypatch.setattr(db, "pool", fake_pool)

    await db.fetch_recent_payslips("paluss", limit=2)

    query = conn.sql[0]
    assert "FROM payslips" in query
    assert "chro." not in query
    assert "human_res." not in query
    assert conn.args[0][0] == db.DEFAULT_HR_USER_ID


def test_hr_user_alias_maps_paluss_to_uuid():
    assert db.resolve_hr_user_id("paluss") == db.DEFAULT_HR_USER_ID
    assert db.resolve_hr_user_id("me") == db.DEFAULT_HR_USER_ID
    assert db.resolve_hr_user_id("75f9a1ac-e4ca-41cd-8d2b-1f393db7e732") == (
        "75f9a1ac-e4ca-41cd-8d2b-1f393db7e732"
    )


def test_query_db_normalizes_legacy_schema_qualifiers():
    sql = (
        "SELECT period_to, net_pay FROM human_res.payslips "
        "UNION ALL SELECT period_to, net_pay FROM chro.payslips"
    )

    normalized = _normalize_chro_sql(sql)

    assert "human_res." not in normalized
    assert "chro." not in normalized
    assert normalized.count("FROM payslips") == 2


def test_net_pay_anomaly_cron_uses_migrated_columns():
    prompt = _cron("net_pay_anomaly_alert")["prompt"]

    assert "COALESCE(net_pay, net_amount)" in prompt
    assert "ORDER BY COALESCE(period_to" in prompt
    assert "human_res.payslips" not in prompt
    assert "chro.payslips" not in prompt


def test_chro_normalizes_flight_activities_table_name():
    assert _normalize_chro_sql("SELECT * FROM human_res.flight_activities") == "SELECT * FROM flight_activities"
    assert _normalize_chro_sql("SELECT * FROM chro.flight_activities") == "SELECT * FROM flight_activities"


def test_chro_write_db_mentions_flight_activities():
    from agents.chro.tools import create_chro_mcp_server

    server = create_chro_mcp_server(Path("/tmp/chro"))
    write_tool = next(entry for entry in server._tools if entry.name == "write_db")

    assert "flight_activities" in write_tool.description


@pytest.mark.asyncio
async def test_chro_write_db_coerces_flight_activity_uuid_and_datetimes(monkeypatch):
    from agents.chro.tools import create_chro_mcp_server

    captured = {}

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, sql, *args):
            captured["sql"] = sql
            captured["args"] = args
            return {"id": uuid.uuid4()}

        async def execute(self, *args):
            return "INSERT 0 1"

        async def close(self):
            return None

    async def fake_connect(url):
        return FakeConn()

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=fake_connect))
    monkeypatch.setenv("CHRO_POSTGRES_URL", "postgres://chro")

    server = create_chro_mcp_server(Path("/tmp/chro"))
    write_tool = next(entry for entry in server._tools if entry.name == "write_db")
    user_id = "75f9a1ac-e4ca-41cd-8d2b-1f393db7e732"

    result = await write_tool.fn({
        "action": "insert",
        "table": "flight_activities",
        "fields": {
            "user_id": user_id,
            "takeoff_time": "2026-05-07T11:30:00+02:00",
            "landing_time": "2026-05-07T12:30:00+02:00",
            "flight_duration": 60,
        },
    })

    assert "OK action=insert table=flight_activities" in result["content"][0]["text"]
    assert "INSERT INTO flight_activities" in captured["sql"]
    assert captured["args"][0] == uuid.UUID(user_id)
    assert captured["args"][1].isoformat() == "2026-05-07T11:30:00+02:00"
    assert captured["args"][2].isoformat() == "2026-05-07T12:30:00+02:00"
