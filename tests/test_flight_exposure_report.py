from unittest.mock import AsyncMock

import pytest

from agents.coh.flight_exposure import build_whoop_impact_report


class FakeConn:
    def __init__(self):
        self.fetchrow_args = None
        self.fetch_args = None
        self.fetchrow = AsyncMock(return_value={"id": "flight-1", "takeoff_at": "2026-05-07T11:30:00+02:00"})
        self.fetch = AsyncMock(return_value=[])

    async def record_fetchrow(self, sql, *args):
        self.fetchrow_args = args
        return {"id": "flight-1", "takeoff_at": "2026-05-07T11:30:00+02:00"}

    async def record_fetch(self, sql, *args):
        self.fetch_args = args
        return []


@pytest.mark.asyncio
async def test_whoop_report_returns_insufficient_data_without_observations():
    result = await build_whoop_impact_report(
        FakeConn(),
        flight_id="flight-1",
        flight_user_id="75f9a1ac-e4ca-41cd-8d2b-1f393db7e732",
        whoop_user_id=1,
    )

    assert result["status"] == "insufficient_data"
    assert result["flight_id"] == "flight-1"
    assert "missing WHOOP" in result["reason"]


@pytest.mark.asyncio
async def test_whoop_report_uses_uuid_for_flight_and_integer_for_observations():
    conn = FakeConn()
    conn.fetchrow = AsyncMock(side_effect=conn.record_fetchrow)
    conn.fetch = AsyncMock(side_effect=conn.record_fetch)
    flight_user_id = "75f9a1ac-e4ca-41cd-8d2b-1f393db7e732"

    await build_whoop_impact_report(
        conn,
        flight_id="flight-1",
        flight_user_id=flight_user_id,
        whoop_user_id=1,
    )

    assert conn.fetchrow_args == ("flight-1", flight_user_id)
    assert conn.fetch_args[0] == 1
