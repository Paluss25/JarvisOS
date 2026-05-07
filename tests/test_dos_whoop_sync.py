import asyncio
import datetime as dt
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


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


def test_whoop_client_fetches_paginated_recovery_sleep_cycle_and_workout(monkeypatch):
    from agents.dos.whoop_sync import WhoopClient, WhoopConfig

    seen_paths = []
    seen_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append((request.url.path, dict(request.url.params)))
        seen_headers.append(dict(request.headers))
        if request.url.path == "/developer/v2/recovery":
            if request.url.params.get("nextToken") == "page-2":
                return httpx.Response(200, json={"records": [{"cycle_id": 2}], "next_token": None})
            return httpx.Response(200, json={"records": [{"cycle_id": 1}], "next_token": "page-2"})
        if request.url.path == "/developer/v2/activity/sleep":
            return httpx.Response(200, json={"records": [{"id": "sleep-1"}]})
        if request.url.path == "/developer/v2/cycle":
            return httpx.Response(200, json={"records": [{"id": 1}]})
        if request.url.path == "/developer/v2/activity/workout":
            return httpx.Response(200, json={"records": [{"id": "workout-1"}]})
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = WhoopClient(
        WhoopConfig(access_token="token"),
        transport=httpx.MockTransport(handler),
    )

    bundle = _run(client.fetch_bundle(
        start=dt.datetime(2026, 5, 6, tzinfo=dt.timezone.utc),
        end=dt.datetime(2026, 5, 7, tzinfo=dt.timezone.utc),
    ))

    assert [row["cycle_id"] for row in bundle.recoveries] == [1, 2]
    assert bundle.sleeps == [{"id": "sleep-1"}]
    assert bundle.cycles == [{"id": 1}]
    assert bundle.workouts == [{"id": "workout-1"}]
    assert ("/developer/v2/recovery", {"limit": "25", "start": "2026-05-06T00:00:00+00:00", "end": "2026-05-07T00:00:00+00:00"}) in seen_paths
    assert seen_headers[0]["accept"] == "application/json"
    assert "Mozilla/5.0" in seen_headers[0]["user-agent"]


def test_whoop_client_refresh_uses_browser_compatible_headers(monkeypatch):
    from agents.dos import whoop_sync
    from agents.dos.whoop_sync import WhoopClient, WhoopConfig

    seen = {}
    writes = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_in": 3600,
            },
        )

    client = WhoopClient(
        WhoopConfig(
            client_id="client",
            client_secret="secret",
            refresh_token="refresh-old",
        ),
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(whoop_sync, "_write_env_value", lambda name, value: writes.append((name, value)))

    token = _run(client._refresh_token())

    assert token == "access-new"
    assert seen["headers"]["accept"] == "application/json"
    assert "Mozilla/5.0" in seen["headers"]["user-agent"]
    assert ("WHOOP_REFRESH_TOKEN", "refresh-new") in writes


def test_import_whoop_bundle_upserts_raw_observation_and_activity_rows():
    from agents.dos.whoop_sync import WhoopBundle, import_whoop_bundle

    conn = MagicMock()
    conn.transaction = MagicMock(return_value=FakeTransaction())
    conn.fetchrow = AsyncMock(side_effect=[None, {"id": 42}])
    conn.execute = AsyncMock()

    bundle = WhoopBundle(
        recoveries=[{
            "cycle_id": 93845,
            "sleep_id": "sleep-1",
            "score_state": "SCORED",
            "score": {
                "recovery_score": 72,
                "resting_heart_rate": 51,
                "hrv_rmssd_milli": 64.8,
                "spo2_percentage": 97.1,
                "skin_temp_celsius": 36.2,
            },
        }],
        sleeps=[{
            "id": "sleep-1",
            "start": "2026-05-05T22:30:00Z",
            "end": "2026-05-06T06:45:00Z",
            "score_state": "SCORED",
            "score": {
                "stage_summary": {
                    "total_light_sleep_time_milli": 12_600_000,
                    "total_slow_wave_sleep_time_milli": 5_400_000,
                    "total_rem_sleep_time_milli": 4_800_000,
                    "total_awake_time_milli": 900_000,
                },
                "sleep_performance_percentage": 88,
            },
        }],
        cycles=[{
            "id": 93845,
            "start": "2026-05-05T08:00:00Z",
            "end": "2026-05-06T08:00:00Z",
            "score_state": "SCORED",
            "score": {"strain": 9.2, "average_heart_rate": 70, "max_heart_rate": 151},
        }],
        workouts=[{
            "id": "workout-1",
            "sport_name": "running",
            "start": "2026-05-06T18:00:00Z",
            "end": "2026-05-06T18:45:00Z",
            "score_state": "SCORED",
            "score": {
                "strain": 8.2,
                "average_heart_rate": 133,
                "max_heart_rate": 166,
                "kilojoule": 1800,
                "distance_meter": 7000,
                "altitude_gain_meter": 70,
            },
        }],
    )

    result = _run(import_whoop_bundle(conn, bundle, user_id=1))

    assert result["observations_upserted"] == 1
    assert result["raw_recoveries_upserted"] == 1
    assert result["activities_inserted"] == 1
    raw_sql = conn.execute.await_args_list[0].args[0]
    observation_sql = conn.execute.await_args_list[3].args[0]
    activity_sql = conn.fetchrow.await_args.args[0]
    assert "INSERT INTO whoop_recoveries" in raw_sql
    assert "INSERT INTO daily_recovery_observations" in observation_sql
    assert "INSERT INTO activities" in activity_sql
    assert conn.execute.await_args_list[3].args[1:18] == (
        dt.date(2026, 5, 6), 1, "whoop_api_v2", 72, 51, 65, 380, 90, 80, 210, 15, "ok",
        97.1, 36.2, 9.2, 70, 151,
    )


def test_whoop_sync_tool_is_registered():
    from agents.dos.tools import create_chief_mcp_server

    server = create_chief_mcp_server(Path("/tmp"), redis_a2a=None)
    names = {tool.name for tool in server._tools}

    assert "whoop_sync" in names
