"""Flight exposure command parsing and persistence helpers for COH."""

from __future__ import annotations

import datetime as dt
import json
import re
import zoneinfo
from dataclasses import dataclass
from typing import Any


ROME = zoneinfo.ZoneInfo("Europe/Rome")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
ICAO_RE = re.compile(r"^[A-Z]{4}$", re.IGNORECASE)
AIRCRAFT_RE = re.compile(r"^[A-Z]{1,3}-?\d{1,3}[A-Z]?$", re.IGNORECASE)
EXPERIMENTAL_TRUE = {
    ("experimental", "yes"),
    ("experimental", "true"),
    ("sperimentale", "si"),
    ("sperimentale", "sì"),
}
EXPERIMENTAL_FALSE = {
    ("experimental", "no"),
    ("experimental", "false"),
    ("sperimentale", "no"),
}


@dataclass(frozen=True)
class ParsedFlightCommand:
    command: str
    event_time: dt.datetime
    icao: str | None
    aircraft_type: str | None
    flight_type: str | None
    experimental: bool
    raw_command: str
    experimental_provided: bool = False


def _parse_time(token: str, now: dt.datetime) -> dt.datetime | None:
    if not TIME_RE.match(token):
        return None
    hour_s, minute_s = token.split(":", 1)
    hour = int(hour_s)
    minute = int(minute_s)
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid time: {token}")
    local_now = now.astimezone(ROME)
    parsed = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if parsed > local_now.replace(second=0, microsecond=0):
        parsed -= dt.timedelta(days=1)
    return parsed


def _extract_experimental(tokens: list[str]) -> tuple[bool, bool, list[str]]:
    kept: list[str] = []
    experimental = True
    provided = False
    idx = 0
    while idx < len(tokens):
        pair = (tokens[idx].lower(), tokens[idx + 1].lower()) if idx + 1 < len(tokens) else None
        if pair in EXPERIMENTAL_TRUE:
            experimental = True
            provided = True
            idx += 2
            continue
        if pair in EXPERIMENTAL_FALSE:
            experimental = False
            provided = True
            idx += 2
            continue
        kept.append(tokens[idx])
        idx += 1
    return experimental, provided, kept


def parse_flight_command(
    text: str,
    command: str,
    *,
    now: dt.datetime | None = None,
) -> ParsedFlightCommand:
    now = now or dt.datetime.now(tz=ROME)
    raw = (text or "").strip()
    tokens = raw.split()

    event_time = now.astimezone(ROME).replace(second=0, microsecond=0)
    if tokens:
        parsed_time = _parse_time(tokens[0], now)
        if parsed_time is not None:
            event_time = parsed_time
            tokens = tokens[1:]

    experimental, experimental_provided, tokens = _extract_experimental(tokens)

    icao = None
    aircraft_type = None
    remaining: list[str] = []
    for token in tokens:
        if icao is None and ICAO_RE.match(token):
            icao = token.upper()
            continue
        if aircraft_type is None and AIRCRAFT_RE.match(token):
            aircraft_type = token.upper()
            continue
        remaining.append(token)

    flight_type = " ".join(remaining).strip() or None
    return ParsedFlightCommand(
        command=command,
        event_time=event_time,
        icao=icao,
        aircraft_type=aircraft_type,
        flight_type=flight_type,
        experimental=experimental,
        raw_command=raw,
        experimental_provided=experimental_provided,
    )


def _duration(start: dt.datetime, end: dt.datetime) -> int:
    delta = end - start
    minutes = int(delta.total_seconds() // 60)
    if minutes <= 0:
        raise ValueError("landing time must be after takeoff time")
    return minutes


class FlightExposureService:
    def __init__(
        self,
        *,
        sport_conn: Any,
        chro_conn: Any | None,
        sport_user_id: str,
        chro_user_id: str | None,
    ):
        self.sport_conn = sport_conn
        self.chro_conn = chro_conn
        self.sport_user_id = sport_user_id
        self.chro_user_id = chro_user_id
        self.last_payload: dict[str, Any] = {}

    async def _open_flight(self) -> dict[str, Any] | None:
        row = await self.sport_conn.fetchrow(
            """
            SELECT id, source_ref, takeoff_at, aircraft_type, flight_type, experimental
            FROM flight_exposures
            WHERE user_id = $1 AND status = 'open'
            ORDER BY takeoff_at DESC
            LIMIT 1
            """,
            self.sport_user_id,
        )
        return dict(row) if row else None

    async def takeoff(self, parsed: ParsedFlightCommand) -> dict[str, Any]:
        open_row = await self._open_flight()
        if open_row:
            return {"status": "error", "code": "flight_already_open", "open_flight": open_row}

        chro_id = None
        if self.chro_conn is not None:
            chro_row = await self.chro_conn.fetchrow(
                """
                INSERT INTO chro.flight_activities
                    (user_id, takeoff_time, takeoff_icao, aircraft_type, flight_type,
                     experimental, status, source, notes, raw_command)
                VALUES ($1,$2,$3,$4,$5,$6,'open','telegram_coh',$7,$8)
                RETURNING id
                """,
                self.chro_user_id,
                parsed.event_time,
                parsed.icao,
                parsed.aircraft_type,
                parsed.flight_type,
                parsed.experimental,
                parsed.flight_type,
                parsed.raw_command,
            )
            chro_id = str(chro_row["id"])

        raw_context = {
            "raw_command": parsed.raw_command,
            "command": parsed.command,
        }
        try:
            sport_row = await self.sport_conn.fetchrow(
                """
                INSERT INTO flight_exposures
                    (user_id, takeoff_at, takeoff_icao, aircraft_type, flight_type,
                     experimental, status, source, source_ref, notes, raw_context)
                VALUES ($1,$2,$3,$4,$5,$6,'open','telegram_coh',$7,$8,$9::jsonb)
                RETURNING id
                """,
                self.sport_user_id,
                parsed.event_time,
                parsed.icao,
                parsed.aircraft_type,
                parsed.flight_type,
                parsed.experimental,
                chro_id,
                parsed.flight_type,
                json.dumps(raw_context),
            )
        except Exception:
            if self.chro_conn is not None and chro_id is not None:
                await self.chro_conn.execute(
                    """
                    UPDATE chro.flight_activities
                    SET status = 'cancelled',
                        notes = COALESCE(notes || '\n', '') || 'sport insert failed after CHRO pre-write',
                        updated_at = now()
                    WHERE id = $1 AND status = 'open'
                    """,
                    chro_id,
                )
            raise
        return {"status": "open", "sport_id": str(sport_row["id"]), "chro_id": chro_id}

    async def landing(self, parsed: ParsedFlightCommand) -> dict[str, Any]:
        open_row = await self._open_flight()
        if not open_row:
            return {"status": "error", "code": "no_open_flight"}

        duration = _duration(open_row["takeoff_at"], parsed.event_time)
        aircraft_type = open_row.get("aircraft_type") or parsed.aircraft_type
        flight_type = open_row.get("flight_type") or parsed.flight_type
        experimental = parsed.experimental if parsed.experimental_provided else open_row.get("experimental", True)

        payload = {
            "duration": duration,
            "landing_icao": parsed.icao,
            "aircraft_type": aircraft_type,
            "flight_type": flight_type,
            "experimental": experimental,
            "raw_command": parsed.raw_command,
        }
        self.last_payload = payload
        if self.chro_conn is not None and open_row.get("source_ref"):
            await self.chro_conn.fetchrow(
                """
                UPDATE chro.flight_activities
                SET landing_time = $2,
                    flight_duration = $3,
                    landing_icao = COALESCE($4, landing_icao),
                    aircraft_type = COALESCE($5, aircraft_type),
                    flight_type = COALESCE($6, flight_type),
                    experimental = COALESCE($7, experimental),
                    status = 'closed',
                    updated_at = now()
                WHERE id = $1
                RETURNING id
                """,
                open_row["source_ref"],
                parsed.event_time,
                duration,
                parsed.icao,
                payload["aircraft_type"],
                payload["flight_type"],
                payload["experimental"],
            )
        await self.sport_conn.fetchrow(
            """
            UPDATE flight_exposures
            SET landing_at = $2,
                duration = $3,
                landing_icao = COALESCE($4, landing_icao),
                aircraft_type = COALESCE($5, aircraft_type),
                flight_type = COALESCE($6, flight_type),
                experimental = COALESCE($7, experimental),
                status = 'closed',
                raw_context = raw_context || $8::jsonb,
                updated_at = now()
            WHERE id = $1
            RETURNING id, duration
            """,
            open_row["id"],
            parsed.event_time,
            duration,
            parsed.icao,
            payload["aircraft_type"],
            payload["flight_type"],
            payload["experimental"],
            json.dumps({"landing_raw_command": parsed.raw_command}),
        )
        return {"status": "closed", "sport_id": str(open_row["id"]), "duration": duration}
