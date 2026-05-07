"""Flight exposure command parsing and persistence helpers for COH."""

from __future__ import annotations

import datetime as dt
import re
import zoneinfo
from dataclasses import dataclass


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


def _extract_experimental(tokens: list[str]) -> tuple[bool, list[str]]:
    kept: list[str] = []
    experimental = True
    idx = 0
    while idx < len(tokens):
        pair = (tokens[idx].lower(), tokens[idx + 1].lower()) if idx + 1 < len(tokens) else None
        if pair in EXPERIMENTAL_TRUE:
            experimental = True
            idx += 2
            continue
        if pair in EXPERIMENTAL_FALSE:
            experimental = False
            idx += 2
            continue
        kept.append(tokens[idx])
        idx += 1
    return experimental, kept


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

    experimental, tokens = _extract_experimental(tokens)

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
    )
