import datetime as dt
import sys
import types
import zoneinfo
from unittest.mock import AsyncMock

import pytest

from agents.coh.flight_exposure import FlightExposureService, parse_flight_command


ROME = zoneinfo.ZoneInfo("Europe/Rome")


class FakeConn:
    def __init__(self, *, open_row=None, name="conn", events=None, fail_sport_insert=False):
        self.open_row = open_row
        self.name = name
        self.events = events
        self.fail_sport_insert = fail_sport_insert
        self.fetchrow = AsyncMock(side_effect=self._fetchrow)
        self.execute = AsyncMock(return_value="UPDATE 1")

    async def _fetchrow(self, sql, *args):
        if self.events is not None:
            self.events.append((self.name, sql))
        if "FROM flight_exposures" in sql and "status = 'open'" in sql:
            return self.open_row
        if "INSERT INTO flight_exposures" in sql:
            if self.fail_sport_insert:
                raise RuntimeError("sport insert failed")
            return {"id": "sport-flight-1"}
        if "UPDATE flight_exposures" in sql:
            return {"id": "sport-flight-1", "duration": 60}
        if "INSERT INTO chro.flight_activities" in sql:
            return {"id": "chro-flight-1"}
        if "UPDATE chro.flight_activities" in sql:
            return {"id": "chro-flight-1"}
        return None


@pytest.mark.asyncio
async def test_takeoff_creates_sport_then_chro_rows():
    events = []
    sport = FakeConn(name="sport", events=events)
    chro = FakeConn(name="chro", events=events)
    service = FlightExposureService(
        sport_conn=sport,
        chro_conn=chro,
        sport_user_id=1,
        chro_user_id="75f9",
    )
    parsed = parse_flight_command(
        "11:30 M-346 Handling Qualities",
        command="decollo",
        now=dt.datetime(2026, 5, 7, 15, 0, tzinfo=ROME),
    )

    result = await service.takeoff(parsed)

    assert result["status"] == "open"
    assert result["sport_id"] == "sport-flight-1"
    assert result["chro_id"] == "chro-flight-1"
    assert sport.fetchrow.await_count == 2
    assert chro.fetchrow.await_count == 1
    assert [event[0] for event in events] == ["sport", "chro", "sport"]
    sport_insert = sport.fetchrow.await_args_list[1].args
    assert "source_ref" in sport_insert[0]
    assert sport_insert[1] == 1
    assert sport_insert[2] == "75f9"
    assert sport_insert[8] == "chro-flight-1"
    assert sport.execute.await_count == 0


@pytest.mark.asyncio
async def test_takeoff_cancels_chro_row_when_sport_insert_fails():
    sport = FakeConn(fail_sport_insert=True)
    chro = FakeConn()
    service = FlightExposureService(
        sport_conn=sport,
        chro_conn=chro,
        sport_user_id=1,
        chro_user_id="75f9",
    )
    parsed = parse_flight_command(
        "11:30 M-346",
        command="decollo",
        now=dt.datetime(2026, 5, 7, 15, 0, tzinfo=ROME),
    )

    with pytest.raises(RuntimeError, match="sport insert failed"):
        await service.takeoff(parsed)

    assert chro.execute.await_count == 1
    assert "status = 'cancelled'" in chro.execute.await_args.args[0]


@pytest.mark.asyncio
async def test_takeoff_rejects_existing_open_flight():
    open_row = {"id": "existing", "takeoff_at": dt.datetime(2026, 5, 7, 10, 0, tzinfo=ROME)}
    service = FlightExposureService(
        sport_conn=FakeConn(open_row=open_row),
        chro_conn=FakeConn(),
        sport_user_id=1,
        chro_user_id="75f9",
    )
    parsed = parse_flight_command(
        "11:30 M-346",
        command="decollo",
        now=dt.datetime(2026, 5, 7, 15, 0, tzinfo=ROME),
    )

    result = await service.takeoff(parsed)

    assert result["status"] == "error"
    assert result["code"] == "flight_already_open"


@pytest.mark.asyncio
async def test_landing_closes_open_flight_and_computes_duration():
    events = []
    open_row = {
        "id": "sport-flight-1",
        "source_ref": "chro-flight-1",
        "takeoff_at": dt.datetime(2026, 5, 7, 11, 30, tzinfo=ROME),
        "aircraft_type": None,
        "flight_type": None,
        "experimental": True,
    }
    service = FlightExposureService(
        sport_conn=FakeConn(open_row=open_row, name="sport", events=events),
        chro_conn=FakeConn(name="chro", events=events),
        sport_user_id=1,
        chro_user_id="75f9",
    )
    parsed = parse_flight_command(
        "12:30 LIRE M-346 Handling Qualities",
        command="atterraggio",
        now=dt.datetime(2026, 5, 7, 15, 0, tzinfo=ROME),
    )

    result = await service.landing(parsed)

    assert result["status"] == "closed"
    assert result["duration"] == 60
    assert service.last_payload["duration"] == 60
    assert service.last_payload["landing_icao"] == "LIRE"
    assert service.last_payload["aircraft_type"] == "M-346"
    assert service.last_payload["flight_type"] == "Handling Qualities"
    assert service.last_payload["experimental"] is True
    assert [event[0] for event in events] == ["sport", "chro", "sport"]


@pytest.mark.asyncio
async def test_landing_preserves_existing_details_when_landing_command_has_new_values():
    open_row = {
        "id": "sport-flight-1",
        "source_ref": "chro-flight-1",
        "takeoff_at": dt.datetime(2026, 5, 7, 11, 30, tzinfo=ROME),
        "aircraft_type": "M-346",
        "flight_type": "Handling Qualities",
        "experimental": False,
    }
    service = FlightExposureService(
        sport_conn=FakeConn(open_row=open_row),
        chro_conn=FakeConn(),
        sport_user_id=1,
        chro_user_id="75f9",
    )
    parsed = parse_flight_command(
        "12:30 LIRE F-35 Functional Check",
        command="atterraggio",
        now=dt.datetime(2026, 5, 7, 15, 0, tzinfo=ROME),
    )

    result = await service.landing(parsed)

    assert result["status"] == "closed"
    assert service.last_payload["aircraft_type"] == "M-346"
    assert service.last_payload["flight_type"] == "Handling Qualities"
    assert service.last_payload["experimental"] is False


@pytest.mark.asyncio
async def test_landing_explicit_experimental_can_correct_takeoff_default():
    open_row = {
        "id": "sport-flight-1",
        "source_ref": "chro-flight-1",
        "takeoff_at": dt.datetime(2026, 5, 7, 11, 30, tzinfo=ROME),
        "aircraft_type": "M-346",
        "flight_type": "Handling Qualities",
        "experimental": True,
    }
    service = FlightExposureService(
        sport_conn=FakeConn(open_row=open_row),
        chro_conn=FakeConn(),
        sport_user_id=1,
        chro_user_id="75f9",
    )
    parsed = parse_flight_command(
        "12:30 experimental no",
        command="atterraggio",
        now=dt.datetime(2026, 5, 7, 15, 0, tzinfo=ROME),
    )

    result = await service.landing(parsed)

    assert result["status"] == "closed"
    assert service.last_payload["experimental"] is False


@pytest.mark.asyncio
async def test_landing_rejects_missing_open_flight():
    service = FlightExposureService(
        sport_conn=FakeConn(open_row=None),
        chro_conn=FakeConn(),
        sport_user_id=1,
        chro_user_id="75f9",
    )
    parsed = parse_flight_command(
        "12:30",
        command="atterraggio",
        now=dt.datetime(2026, 5, 7, 15, 0, tzinfo=ROME),
    )

    result = await service.landing(parsed)

    assert result["status"] == "error"
    assert result["code"] == "no_open_flight"


@pytest.mark.asyncio
async def test_status_returns_open_flight():
    open_row = {"id": "sport-flight-1", "takeoff_at": dt.datetime(2026, 5, 7, 11, 30, tzinfo=ROME)}
    service = FlightExposureService(
        sport_conn=FakeConn(open_row=open_row),
        chro_conn=FakeConn(),
        sport_user_id=1,
        chro_user_id="75f9",
    )

    result = await service.status()

    assert result["status"] == "open"
    assert result["flight"]["id"] == "sport-flight-1"


@pytest.mark.asyncio
async def test_cancel_marks_open_flight_cancelled():
    open_row = {
        "id": "sport-flight-1",
        "source_ref": "chro-flight-1",
        "takeoff_at": dt.datetime(2026, 5, 7, 11, 30, tzinfo=ROME),
    }
    sport = FakeConn(open_row=open_row)
    chro = FakeConn()
    service = FlightExposureService(
        sport_conn=sport,
        chro_conn=chro,
        sport_user_id=1,
        chro_user_id="75f9",
    )

    result = await service.cancel("errore inserimento")

    assert result["status"] == "cancelled"
    sport_cancel_sql = sport.execute.await_args.args[0]
    chro_cancel_sql = chro.execute.await_args.args[0]
    assert "status = 'cancelled'" in sport_cancel_sql
    assert "status = 'cancelled'" in chro_cancel_sql


def _tool_names(server):
    return {entry.name for entry in server._tools}


def test_coh_registers_flight_tools(tmp_path):
    from agents.coh.tools import create_drhouse_mcp_server

    server = create_drhouse_mcp_server(tmp_path)

    names = _tool_names(server)
    assert "flight_takeoff" in names
    assert "flight_landing" in names
    assert "flight_status" in names
    assert "flight_cancel" in names
    assert "flight_report" in names


@pytest.mark.asyncio
async def test_flight_tool_closes_sport_connection_when_chro_connect_fails(monkeypatch, tmp_path):
    from agents.coh.tools import create_drhouse_mcp_server

    closed = []

    class FakeAsyncpgConn:
        async def close(self):
            closed.append("sport")

    async def fake_connect(url):
        if url == "sport-dsn":
            return FakeAsyncpgConn()
        raise RuntimeError("chro connect failed")

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=fake_connect))
    monkeypatch.setenv("DRHOUSE_SPORT_POSTGRES_URL", "sport-dsn")
    monkeypatch.setenv("CHRO_POSTGRES_URL", "chro-dsn")

    server = create_drhouse_mcp_server(tmp_path)
    tool = next(entry for entry in server._tools if entry.name == "flight_status")

    with pytest.raises(RuntimeError, match="chro connect failed"):
        await tool.fn({})

    assert closed == ["sport"]
