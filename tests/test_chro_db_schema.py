"""Tests for CHRO human_res schema compatibility."""

import pytest

from agents.chro import db
from agents.chro.config import CHRO_BUILTIN_CRONS
from agents.chro.tools import _normalize_chro_sql, create_chro_mcp_server


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


@pytest.mark.asyncio
async def test_query_db_preflights_leave_snapshot_column_aliases(tmp_path):
    server = create_chro_mcp_server(tmp_path)
    query_db = next(tool for tool in server._tools if tool.name == "query_db")

    result = await query_db.fn({
        "query": "SELECT snapshot_date, remaining_days, used_days FROM leave_snapshots ORDER BY snapshot_date DESC LIMIT 1",
        "params": [],
    })

    assert result["is_error"] is True
    text = result["content"][0]["text"]
    assert "'remaining_days' on table 'leave_snapshots' → use 'ferie_remaining'" in text
    assert "'used_days' on table 'leave_snapshots' → use 'ferie_used'" in text


def test_net_pay_anomaly_cron_uses_migrated_columns():
    prompt = _cron("net_pay_anomaly_alert")["prompt"]

    assert "COALESCE(net_pay, net_amount)" in prompt
    assert "ORDER BY COALESCE(period_to" in prompt
    assert "human_res.payslips" not in prompt
    assert "chro.payslips" not in prompt


def test_weekly_people_brief_uses_live_leave_columns():
    prompt = _cron("weekly_people_brief")["prompt"]

    assert "ferie_remaining" in prompt
    assert "rol_remaining" in prompt
    assert "remaining_days" not in prompt
    assert "used_days" not in prompt
