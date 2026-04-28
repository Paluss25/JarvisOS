"""Garmin FIT import support for DOS.

This module keeps FIT parsing and database import separate from MCP tool
registration so it can be tested without the Claude SDK.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import fitdecode
except ImportError:  # pragma: no cover - exercised in deployed env after dependency install
    fitdecode = None


SEMICIRCLE_TO_DEGREES = 180.0 / (2**31)
DEFAULT_DB_BATCH_SIZE = 1000


@dataclass
class FitActivityData:
    source_path: Path
    file_sha256: str
    file_id: dict[str, Any] = field(default_factory=dict)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    laps: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    raw_summary: dict[str, Any] = field(default_factory=dict)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _field_dict_from_frame(frame: Any) -> tuple[dict[str, Any], dict[str, str | None]]:
    values: dict[str, Any] = {}
    units: dict[str, str | None] = {}
    for field in getattr(frame, "fields", []) or []:
        name = getattr(field, "name", None)
        if not name:
            continue
        values[name] = getattr(field, "value", None)
        units[name] = getattr(field, "units", None)
    return values, units


def _semicircles_to_degrees(value: Any) -> float | None:
    number = _coerce_number(value)
    if number is None:
        return None
    return number * SEMICIRCLE_TO_DEGREES


def _promote_session(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "sport": fields.get("sport"),
        "sub_sport": fields.get("sub_sport"),
        "start_time": fields.get("start_time"),
        "total_elapsed_time_s": fields.get("total_elapsed_time"),
        "total_timer_time_s": fields.get("total_timer_time"),
        "total_distance_m": fields.get("total_distance"),
        "total_calories": fields.get("total_calories"),
        "avg_heart_rate": fields.get("avg_heart_rate"),
        "max_heart_rate": fields.get("max_heart_rate"),
        "avg_cadence": fields.get("avg_cadence"),
        "max_cadence": fields.get("max_cadence"),
        "avg_power": fields.get("avg_power"),
        "max_power": fields.get("max_power"),
        "total_ascent_m": fields.get("total_ascent"),
        "training_effect": fields.get("total_training_effect"),
        "anaerobic_training_effect": fields.get("total_anaerobic_training_effect"),
        "raw_json": _json_safe(fields),
    }


def _promote_lap(fields: dict[str, Any], lap_index: int) -> dict[str, Any]:
    return {
        "lap_index": lap_index,
        "start_time": fields.get("start_time"),
        "total_elapsed_time_s": fields.get("total_elapsed_time"),
        "total_timer_time_s": fields.get("total_timer_time"),
        "total_distance_m": fields.get("total_distance"),
        "total_calories": fields.get("total_calories"),
        "avg_heart_rate": fields.get("avg_heart_rate"),
        "max_heart_rate": fields.get("max_heart_rate"),
        "avg_cadence": fields.get("avg_cadence"),
        "max_cadence": fields.get("max_cadence"),
        "avg_power": fields.get("avg_power"),
        "max_power": fields.get("max_power"),
        "raw_json": _json_safe(fields),
    }


def _promote_record(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": fields.get("timestamp"),
        "position_lat": _semicircles_to_degrees(fields.get("position_lat")),
        "position_long": _semicircles_to_degrees(fields.get("position_long")),
        "distance_m": fields.get("distance"),
        "altitude_m": fields.get("altitude"),
        "heart_rate": fields.get("heart_rate"),
        "cadence": fields.get("cadence"),
        "speed_mps": fields.get("speed"),
        "power_w": fields.get("power"),
        "temperature_c": fields.get("temperature"),
        "fractional_cadence": fields.get("fractional_cadence"),
        "raw_json": _json_safe(fields),
    }


def _generic_field_rows(
    fit_file_message_name: str,
    message_index: int,
    values: dict[str, Any],
    units: dict[str, str | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, value in values.items():
        number = _coerce_number(value)
        rows.append({
            "message_name": fit_file_message_name,
            "message_index": message_index,
            "field_name": field_name,
            "field_value_text": None if number is not None else json.dumps(value, default=_json_default),
            "field_value_num": number,
            "field_unit": units.get(field_name),
        })
    return rows


def parse_fit_file(path: Path) -> FitActivityData:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() != ".fit":
        raise ValueError(f"Expected a .fit file, got: {path}")
    if not path.is_file():
        raise ValueError(f"Expected a regular file, got: {path}")
    if fitdecode is None:
        raise RuntimeError("fitdecode is not installed")

    parsed = FitActivityData(source_path=path, file_sha256=compute_sha256(path))
    message_counts: dict[str, int] = {}
    lap_index = 0

    with fitdecode.FitReader(str(path)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            message_name = getattr(frame, "name", "")
            fields, units = _field_dict_from_frame(frame)
            message_index = message_counts.get(message_name, 0)
            message_counts[message_name] = message_index + 1

            parsed.fields.extend(_generic_field_rows(message_name, message_index, fields, units))

            if message_name == "file_id":
                parsed.file_id.update(fields)
            elif message_name == "session":
                parsed.sessions.append(_promote_session(fields))
            elif message_name == "lap":
                parsed.laps.append(_promote_lap(fields, lap_index))
                lap_index += 1
            elif message_name == "record":
                parsed.records.append(_promote_record(fields))

    parsed.raw_summary = {
        "file_id": _json_safe(parsed.file_id),
        "counts": {
            "sessions": len(parsed.sessions),
            "laps": len(parsed.laps),
            "records": len(parsed.records),
            "fields": len(parsed.fields),
        },
    }
    return parsed


async def resolve_activity_id(
    conn: Any,
    *,
    activity_id: int | None,
    strava_activity_id: int | None,
    user_id: int,
) -> int:
    if activity_id:
        row = await conn.fetchrow(
            "SELECT id FROM activities WHERE id = $1 AND user_id = $2",
            int(activity_id),
            int(user_id),
        )
        lookup = f"activity_id={activity_id}"
    else:
        if not strava_activity_id:
            raise ValueError("activity_id or strava_activity_id is required")
        row = await conn.fetchrow(
            "SELECT id FROM activities WHERE strava_activity_id = $1 AND user_id = $2",
            int(strava_activity_id),
            int(user_id),
        )
        lookup = f"strava_activity_id={strava_activity_id}"
    if not row:
        raise ValueError(f"No activity found for {lookup}")
    return int(row["id"])


def _jsonb(value: Any) -> str:
    return json.dumps(_json_safe(value), default=_json_default)


async def import_fit_data(
    conn: Any,
    parsed: FitActivityData,
    *,
    activity_id: int,
    user_id: int,
) -> dict[str, Any]:
    async with conn.transaction():
        activity_id = await resolve_activity_id(
            conn,
            activity_id=activity_id,
            strava_activity_id=None,
            user_id=user_id,
        )
        file_row = await conn.fetchrow(
            """
            INSERT INTO activity_fit_files
                (activity_id, user_id, source_path, file_sha256, manufacturer, product,
                 serial_number, time_created, raw_summary_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
            ON CONFLICT (file_sha256) DO NOTHING
            RETURNING id
            """,
            activity_id,
            user_id,
            str(parsed.source_path),
            parsed.file_sha256,
            parsed.file_id.get("manufacturer"),
            parsed.file_id.get("product"),
            parsed.file_id.get("serial_number"),
            parsed.file_id.get("time_created"),
            _jsonb(parsed.raw_summary),
        )

        if not file_row:
            existing = await conn.fetchrow(
                "SELECT id, activity_id, user_id FROM activity_fit_files WHERE file_sha256 = $1",
                parsed.file_sha256,
            )
            if not existing:
                raise RuntimeError(f"FIT file insert conflicted but no existing row was found: {parsed.file_sha256}")
            if int(existing["activity_id"]) != activity_id or int(existing["user_id"]) != int(user_id):
                raise ValueError(
                    "FIT file SHA is already linked to a different activity or user: "
                    f"fit_file_id={existing['id']}, activity_id={existing['activity_id']}"
                )
            return {
                "status": "already_exists",
                "fit_file_id": existing["id"],
                "activity_id": existing["activity_id"],
                "sessions": 0,
                "laps": 0,
                "records": 0,
                "fields": 0,
            }
        fit_file_id = int(file_row["id"])

        for session in parsed.sessions:
            await conn.execute(
                """
                INSERT INTO activity_fit_sessions
                    (fit_file_id, activity_id, sport, sub_sport, start_time,
                     total_elapsed_time_s, total_timer_time_s, total_distance_m,
                     total_calories, avg_heart_rate, max_heart_rate, avg_cadence,
                     max_cadence, avg_power, max_power, total_ascent_m,
                     training_effect, anaerobic_training_effect, raw_json)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19::jsonb)
                """,
                fit_file_id,
                activity_id,
                session.get("sport"),
                session.get("sub_sport"),
                session.get("start_time"),
                session.get("total_elapsed_time_s"),
                session.get("total_timer_time_s"),
                session.get("total_distance_m"),
                session.get("total_calories"),
                session.get("avg_heart_rate"),
                session.get("max_heart_rate"),
                session.get("avg_cadence"),
                session.get("max_cadence"),
                session.get("avg_power"),
                session.get("max_power"),
                session.get("total_ascent_m"),
                session.get("training_effect"),
                session.get("anaerobic_training_effect"),
                _jsonb(session.get("raw_json", {})),
            )

        for lap in parsed.laps:
            await conn.execute(
                """
                INSERT INTO activity_fit_laps
                    (fit_file_id, activity_id, lap_index, start_time, total_elapsed_time_s,
                     total_timer_time_s, total_distance_m, total_calories, avg_heart_rate,
                     max_heart_rate, avg_cadence, max_cadence, avg_power, max_power, raw_json)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb)
                """,
                fit_file_id,
                activity_id,
                lap.get("lap_index"),
                lap.get("start_time"),
                lap.get("total_elapsed_time_s"),
                lap.get("total_timer_time_s"),
                lap.get("total_distance_m"),
                lap.get("total_calories"),
                lap.get("avg_heart_rate"),
                lap.get("max_heart_rate"),
                lap.get("avg_cadence"),
                lap.get("max_cadence"),
                lap.get("avg_power"),
                lap.get("max_power"),
                _jsonb(lap.get("raw_json", {})),
            )

        await _insert_record_batches(conn, fit_file_id, activity_id, parsed.records)
        await _insert_field_batches(conn, fit_file_id, activity_id, parsed.fields)

        return {
            "status": "imported",
            "fit_file_id": fit_file_id,
            "activity_id": activity_id,
            "sessions": len(parsed.sessions),
            "laps": len(parsed.laps),
            "records": len(parsed.records),
            "fields": len(parsed.fields),
        }


def _chunks(rows: list[tuple[Any, ...]], batch_size: int) -> list[list[tuple[Any, ...]]]:
    return [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]


async def _insert_record_batches(
    conn: Any,
    fit_file_id: int,
    activity_id: int,
    records: list[dict[str, Any]],
    batch_size: int = DEFAULT_DB_BATCH_SIZE,
) -> None:
    rows = [
        (
            fit_file_id,
            activity_id,
            row.get("timestamp"),
            row.get("position_lat"),
            row.get("position_long"),
            row.get("distance_m"),
            row.get("altitude_m"),
            row.get("heart_rate"),
            row.get("cadence"),
            row.get("speed_mps"),
            row.get("power_w"),
            row.get("temperature_c"),
            row.get("fractional_cadence"),
            _jsonb(row.get("raw_json", {})),
        )
        for row in records
    ]
    for batch in _chunks(rows, batch_size):
        await conn.executemany(
            """
            INSERT INTO activity_fit_records
                (fit_file_id, activity_id, timestamp, position_lat, position_long,
                 distance_m, altitude_m, heart_rate, cadence, speed_mps, power_w,
                 temperature_c, fractional_cadence, raw_json)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
            """,
            batch,
        )


async def _insert_field_batches(
    conn: Any,
    fit_file_id: int,
    activity_id: int,
    fields: list[dict[str, Any]],
    batch_size: int = DEFAULT_DB_BATCH_SIZE,
) -> None:
    rows = [
        (
            fit_file_id,
            activity_id,
            row.get("message_name"),
            row.get("message_index"),
            row.get("field_name"),
            row.get("field_value_text"),
            row.get("field_value_num"),
            row.get("field_unit"),
        )
        for row in fields
    ]
    for batch in _chunks(rows, batch_size):
        await conn.executemany(
            """
            INSERT INTO activity_fit_fields
                (fit_file_id, activity_id, message_name, message_index, field_name,
                 field_value_text, field_value_num, field_unit)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            batch,
        )
