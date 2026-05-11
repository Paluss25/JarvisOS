import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.don.subagents import coach as coach_mod
from agents.don.subagents.coach import HealthCoachAgent


class _FakeConn:
    def __init__(self):
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "FROM daily_summaries" in sql:
            return {"total_calories": 1000, "total_protein": 80}
        return {"calories_target": 2200, "protein_target": 160}

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_health_coach_queries_live_nutrition_schema(monkeypatch):
    conn = _FakeConn()
    asyncpg_mock = MagicMock()
    asyncpg_mock.connect = AsyncMock(return_value=conn)
    monkeypatch.setattr(coach_mod, "asyncpg", asyncpg_mock)

    coach = HealthCoachAgent()
    totals, goals = await coach._fetch_context(user_id=None)

    assert totals["total_calories"] == 1000
    assert goals["calories_target"] == 2200
    daily_sql = conn.calls[0][0]
    goal_sql = conn.calls[1][0]
    assert "WHERE date = $1" in daily_sql
    assert "summary_date" not in daily_sql
    assert "ORDER BY id" not in daily_sql
    assert "SELECT target_calories AS calories_target" in goal_sql
    assert "ORDER BY active_from DESC" in goal_sql
    assert conn.calls[0][1] == (date.today(),)
