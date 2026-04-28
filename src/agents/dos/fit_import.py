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


SEMICIRCLE_TO_DEGREES = 180.0 / (2**31)


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
        "raw_json": fields,
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
        "raw_json": fields,
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
        "raw_json": fields,
    }
