"""Garmin daily fitness FIT import support for DOS.

Daily fitness FIT files contain wellness, sleep, HRV, skin-temperature and
similar records. They are separate from activity FIT files and are linked by
date/user rather than by sport activity.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import fitdecode
except ImportError:  # pragma: no cover - exercised in deployed env after dependency install
    fitdecode = None

from agents.dos.fit_import import (
    DEFAULT_DB_BATCH_SIZE,
    _coerce_number,
    _field_dict_from_frame,
    _generic_field_rows,
    _json_safe,
    _jsonb,
    _optional_text,
    compute_sha256,
)


@dataclass
class DailyFitnessData:
    date: date
    source_folder: Path
    files: list[dict[str, Any]] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    wellness_records: list[dict[str, Any]] = field(default_factory=list)
    stress_records: list[dict[str, Any]] = field(default_factory=list)
    respiration_records: list[dict[str, Any]] = field(default_factory=list)
    sleep_levels: list[dict[str, Any]] = field(default_factory=list)
    hrv_values: list[dict[str, Any]] = field(default_factory=list)
    skin_temp_overnight: list[dict[str, Any]] = field(default_factory=list)
    recovery_summary: dict[str, Any] = field(default_factory=dict)


def _file_kind(path: Path) -> str:
    match = re.match(r"^\d+_(.+)$", path.stem)
    return match.group(1) if match else path.stem


def _avg_int(values: list[Any]) -> int | None:
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numbers:
        return None
    return int(round(sum(numbers) / len(numbers)))


def _max_int(values: list[Any]) -> int | None:
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numbers:
        return None
    return int(round(max(numbers)))


def _min_int(values: list[Any]) -> int | None:
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numbers:
        return None
    return int(round(min(numbers)))


def _valid_stress(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(round(value))
    if 0 <= number <= 100:
        return number
    return None


def _promote_wellness(fields: dict[str, Any], file_sha256: str) -> dict[str, Any]:
    return {
        "file_sha256": file_sha256,
        "timestamp": fields.get("timestamp"),
        "heart_rate": fields.get("heart_rate"),
        "activity_type": _optional_text(fields.get("activity_type")),
        "intensity": fields.get("intensity"),
        "active_calories": fields.get("active_calories"),
        "distance_m": fields.get("distance"),
        "steps": fields.get("steps"),
        "duration_min": fields.get("duration_min"),
        "raw_json": _json_safe(fields),
    }


def _promote_stress(fields: dict[str, Any], file_sha256: str) -> dict[str, Any]:
    return {
        "file_sha256": file_sha256,
        "timestamp": fields.get("stress_level_time") or fields.get("timestamp"),
        "stress_level_value": fields.get("stress_level_value"),
        "raw_json": _json_safe(fields),
    }


def _promote_respiration(fields: dict[str, Any], file_sha256: str) -> dict[str, Any]:
    return {
        "file_sha256": file_sha256,
        "timestamp": fields.get("timestamp"),
        "respiration_rate": fields.get("respiration_rate"),
        "raw_json": _json_safe(fields),
    }


def _promote_sleep_level(fields: dict[str, Any], file_sha256: str) -> dict[str, Any]:
    return {
        "file_sha256": file_sha256,
        "timestamp": fields.get("timestamp"),
        "sleep_level": _optional_text(fields.get("sleep_level")),
        "raw_json": _json_safe(fields),
    }


def _promote_hrv_value(fields: dict[str, Any], file_sha256: str) -> dict[str, Any]:
    return {
        "file_sha256": file_sha256,
        "timestamp": fields.get("timestamp"),
        "value_ms": fields.get("value"),
        "raw_json": _json_safe(fields),
    }


def _promote_skin_temp(fields: dict[str, Any], file_sha256: str) -> dict[str, Any]:
    return {
        "file_sha256": file_sha256,
        "average_deviation_c": fields.get("average_deviation"),
        "average_7_day_deviation_c": fields.get("average_7_day_deviation"),
        "nightly_value_c": fields.get("nightly_value"),
        "raw_json": _json_safe(fields),
    }


def _sleep_minutes_by_level(sleep_levels: list[dict[str, Any]]) -> dict[str, int]:
    levels = sorted(
        [row for row in sleep_levels if isinstance(row.get("timestamp"), datetime) and row.get("sleep_level")],
        key=lambda row: row["timestamp"],
    )
    totals: dict[str, int] = {"light": 0, "deep": 0, "rem": 0, "awake": 0}
    for current, next_row in zip(levels, levels[1:]):
        level = str(current["sleep_level"]).lower()
        if level not in totals:
            continue
        minutes = max(0, int(round((next_row["timestamp"] - current["timestamp"]).total_seconds() / 60)))
        totals[level] += minutes
    return totals


def _build_recovery_summary(parsed: DailyFitnessData) -> dict[str, Any]:
    stress_values = [_valid_stress(row.get("stress_level_value")) for row in parsed.stress_records]
    stress_values = [value for value in stress_values if value is not None]
    sleep_minutes = _sleep_minutes_by_level(parsed.sleep_levels)
    hrv_values = [row.get("value_ms") for row in parsed.hrv_values]
    heart_rates = [
        row.get("heart_rate")
        for row in parsed.wellness_records
        if isinstance(row.get("heart_rate"), (int, float))
        and not isinstance(row.get("heart_rate"), bool)
        and row.get("heart_rate") > 0
    ]

    summary: dict[str, Any] = {
        "stress_avg": _avg_int(stress_values),
        "stress_max": _max_int(stress_values),
        "hrv_overnight_avg": _avg_int(hrv_values),
        "sleep_deep_min": sleep_minutes["deep"] or None,
        "sleep_rem_min": sleep_minutes["rem"] or None,
        "sleep_light_min": sleep_minutes["light"] or None,
        "sleep_awake_min": sleep_minutes["awake"] or None,
        "rhr_overnight": _min_int(heart_rates),
    }
    sleep_duration = sum(v for k, v in sleep_minutes.items() if k != "awake")
    if sleep_duration:
        summary["sleep_duration_min"] = sleep_duration

    # Activity metrics — monitoring records are cumulative daily counters; take the max value.
    steps_vals = [row["steps"] for row in parsed.wellness_records if row.get("steps") is not None]
    dist_vals = [row["distance_m"] for row in parsed.wellness_records if row.get("distance_m") is not None]
    kcal_vals = [row["active_calories"] for row in parsed.wellness_records if row.get("active_calories") is not None]
    active_min_vals = [row["duration_min"] for row in parsed.wellness_records if row.get("duration_min") is not None]

    if steps_vals:
        summary["steps"] = int(max(steps_vals))
    if dist_vals:
        summary["distance_km"] = round(max(dist_vals) / 1000.0, 3)
    if kcal_vals:
        summary["active_kcal"] = int(max(kcal_vals))
    if active_min_vals:
        summary["active_min"] = round(float(max(active_min_vals)), 1)

    # data_quality: flag obvious sensor artifacts so queries can filter them.
    if not parsed.wellness_records and not parsed.stress_records:
        summary["data_quality"] = "incomplete"
    elif summary.get("stress_max") is not None and summary["stress_max"] >= 75:
        summary["data_quality"] = "stress_high_suspect"
    else:
        summary["data_quality"] = "ok"

    return {key: value for key, value in summary.items() if value is not None}


def parse_daily_fitness_folder(folder: Path, *, date: date) -> DailyFitnessData:
    if not folder.exists():
        raise FileNotFoundError(str(folder))
    if not folder.is_dir():
        raise ValueError(f"Expected a directory, got: {folder}")
    if fitdecode is None:
        raise RuntimeError("fitdecode is not installed")

    parsed = DailyFitnessData(date=date, source_folder=folder)

    for path in sorted(folder.glob("*.fit")):
        file_sha256 = compute_sha256(path)
        file_kind = _file_kind(path)
        file_id: dict[str, Any] = {}
        message_counts: dict[str, int] = {}
        file_fields = 0

        with fitdecode.FitReader(str(path)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                message_name = getattr(frame, "name", "")
                fields, units = _field_dict_from_frame(frame)
                message_index = message_counts.get(message_name, 0)
                message_counts[message_name] = message_index + 1

                for row in _generic_field_rows(message_name, message_index, fields, units):
                    row["file_sha256"] = file_sha256
                    parsed.fields.append(row)
                    file_fields += 1

                if message_name == "file_id":
                    file_id.update(fields)
                elif message_name == "monitoring":
                    parsed.wellness_records.append(_promote_wellness(fields, file_sha256))
                elif message_name == "stress_level":
                    parsed.stress_records.append(_promote_stress(fields, file_sha256))
                elif message_name == "respiration_rate":
                    parsed.respiration_records.append(_promote_respiration(fields, file_sha256))
                elif message_name == "sleep_level":
                    parsed.sleep_levels.append(_promote_sleep_level(fields, file_sha256))
                elif message_name == "hrv_value":
                    parsed.hrv_values.append(_promote_hrv_value(fields, file_sha256))
                elif message_name == "skin_temp_overnight":
                    parsed.skin_temp_overnight.append(_promote_skin_temp(fields, file_sha256))

        parsed.files.append({
            "source_path": path,
            "file_sha256": file_sha256,
            "file_kind": file_kind,
            "file_id": file_id,
            "raw_summary": {
                "file_id": _json_safe(file_id),
                "message_counts": message_counts,
                "counts": {"fields": file_fields},
            },
        })

    parsed.recovery_summary = _build_recovery_summary(parsed)
    return parsed


def _rows_for_file_ids(rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("file_sha256") in file_ids_by_sha]


async def import_daily_fitness_data(conn: Any, parsed: DailyFitnessData, *, user_id: int) -> dict[str, Any]:
    async with conn.transaction():
        file_ids_by_sha: dict[str, int] = {}
        files_existing = 0
        for file_info in parsed.files:
            file_id = file_info.get("file_id", {})
            file_row = await conn.fetchrow(
                """
                INSERT INTO daily_fit_files
                    (date, user_id, source_path, file_sha256, file_kind, manufacturer,
                     product, serial_number, time_created, raw_summary_json)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
                ON CONFLICT (file_sha256) DO NOTHING
                RETURNING id
                """,
                parsed.date,
                user_id,
                str(file_info["source_path"]),
                file_info["file_sha256"],
                file_info["file_kind"],
                _optional_text(file_id.get("manufacturer")),
                _optional_text(file_id.get("product") or file_id.get("garmin_product")),
                _optional_text(file_id.get("serial_number")),
                file_id.get("time_created"),
                _jsonb(file_info.get("raw_summary", {})),
            )
            if file_row:
                file_ids_by_sha[file_info["file_sha256"]] = int(file_row["id"])
                continue

            existing = await conn.fetchrow(
                "SELECT id, date, user_id FROM daily_fit_files WHERE file_sha256 = $1",
                file_info["file_sha256"],
            )
            if not existing:
                raise RuntimeError(
                    f"Daily FIT file insert conflicted but no row was found: {file_info['file_sha256']}"
                )
            if existing["date"] != parsed.date or int(existing["user_id"]) != int(user_id):
                raise ValueError(
                    "Daily FIT file SHA is already linked to a different date or user: "
                    f"daily_fit_file_id={existing['id']}, date={existing['date']}"
                )
            files_existing += 1

        await _insert_daily_field_batches(conn, parsed.date, user_id, _rows_for_file_ids(parsed.fields, file_ids_by_sha), file_ids_by_sha)
        await _insert_daily_wellness_batches(conn, parsed.date, user_id, _rows_for_file_ids(parsed.wellness_records, file_ids_by_sha), file_ids_by_sha)
        await _insert_daily_stress_batches(conn, parsed.date, user_id, _rows_for_file_ids(parsed.stress_records, file_ids_by_sha), file_ids_by_sha)
        await _insert_daily_respiration_batches(conn, parsed.date, user_id, _rows_for_file_ids(parsed.respiration_records, file_ids_by_sha), file_ids_by_sha)
        await _insert_daily_sleep_level_batches(conn, parsed.date, user_id, _rows_for_file_ids(parsed.sleep_levels, file_ids_by_sha), file_ids_by_sha)
        await _insert_daily_hrv_batches(conn, parsed.date, user_id, _rows_for_file_ids(parsed.hrv_values, file_ids_by_sha), file_ids_by_sha)
        await _insert_daily_skin_temp_batches(conn, parsed.date, user_id, _rows_for_file_ids(parsed.skin_temp_overnight, file_ids_by_sha), file_ids_by_sha)

        recovery_upserted = False
        recovery_error: str | None = None
        if parsed.recovery_summary:
            try:
                async with conn.transaction():
                    await _upsert_recovery_metrics(conn, parsed.date, user_id, parsed.recovery_summary)
                recovery_upserted = True
            except Exception as exc:
                recovery_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "recovery_metrics upsert failed for %s (user_id=%s): %s — daily_* preserved",
                    parsed.date, user_id, recovery_error,
                )

        return {
            "status": "imported",
            "date": parsed.date.isoformat(),
            "user_id": user_id,
            "files_seen": len(parsed.files),
            "files_imported": len(file_ids_by_sha),
            "files_existing": files_existing,
            "fields": len(_rows_for_file_ids(parsed.fields, file_ids_by_sha)),
            "wellness_records": len(_rows_for_file_ids(parsed.wellness_records, file_ids_by_sha)),
            "stress_records": len(_rows_for_file_ids(parsed.stress_records, file_ids_by_sha)),
            "respiration_records": len(_rows_for_file_ids(parsed.respiration_records, file_ids_by_sha)),
            "sleep_levels": len(_rows_for_file_ids(parsed.sleep_levels, file_ids_by_sha)),
            "hrv_values": len(_rows_for_file_ids(parsed.hrv_values, file_ids_by_sha)),
            "skin_temp_overnight": len(_rows_for_file_ids(parsed.skin_temp_overnight, file_ids_by_sha)),
            "recovery_summary": parsed.recovery_summary,
            "recovery_metrics_upserted": recovery_upserted,
            "recovery_metrics_error": recovery_error,
        }


def _chunks(rows: list[tuple[Any, ...]], batch_size: int) -> list[list[tuple[Any, ...]]]:
    return [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]


async def _insert_daily_field_batches(conn: Any, import_date: date, user_id: int, rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int], batch_size: int = DEFAULT_DB_BATCH_SIZE) -> None:
    values = [(
        file_ids_by_sha[row["file_sha256"]], import_date, user_id, row.get("message_name"), row.get("message_index"),
        row.get("field_name"), row.get("field_value_text"), row.get("field_value_num"), row.get("field_unit"),
    ) for row in rows]
    for batch in _chunks(values, batch_size):
        await conn.executemany(
            """
            INSERT INTO daily_fit_fields
                (fit_file_id, date, user_id, message_name, message_index, field_name,
                 field_value_text, field_value_num, field_unit)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            batch,
        )


async def _insert_daily_wellness_batches(conn: Any, import_date: date, user_id: int, rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int], batch_size: int = DEFAULT_DB_BATCH_SIZE) -> None:
    values = [(
        file_ids_by_sha[row["file_sha256"]], import_date, user_id, row.get("timestamp"), row.get("heart_rate"),
        row.get("activity_type"), row.get("intensity"), row.get("active_calories"), row.get("distance_m"),
        row.get("steps"), row.get("duration_min"), _jsonb(row.get("raw_json", {})),
    ) for row in rows]
    for batch in _chunks(values, batch_size):
        await conn.executemany(
            """
            INSERT INTO daily_wellness_records
                (fit_file_id, date, user_id, timestamp, heart_rate, activity_type, intensity,
                 active_calories, distance_m, steps, duration_min, raw_json)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
            """,
            batch,
        )


async def _insert_daily_stress_batches(conn: Any, import_date: date, user_id: int, rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int], batch_size: int = DEFAULT_DB_BATCH_SIZE) -> None:
    values = [(
        file_ids_by_sha[row["file_sha256"]], import_date, user_id, row.get("timestamp"),
        row.get("stress_level_value"), _jsonb(row.get("raw_json", {})),
    ) for row in rows]
    for batch in _chunks(values, batch_size):
        await conn.executemany(
            """
            INSERT INTO daily_stress_records
                (fit_file_id, date, user_id, timestamp, stress_level_value, raw_json)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb)
            """,
            batch,
        )


async def _insert_daily_respiration_batches(conn: Any, import_date: date, user_id: int, rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int], batch_size: int = DEFAULT_DB_BATCH_SIZE) -> None:
    values = [(
        file_ids_by_sha[row["file_sha256"]], import_date, user_id, row.get("timestamp"),
        row.get("respiration_rate"), _jsonb(row.get("raw_json", {})),
    ) for row in rows]
    for batch in _chunks(values, batch_size):
        await conn.executemany(
            """
            INSERT INTO daily_respiration_records
                (fit_file_id, date, user_id, timestamp, respiration_rate, raw_json)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb)
            """,
            batch,
        )


async def _insert_daily_sleep_level_batches(conn: Any, import_date: date, user_id: int, rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int], batch_size: int = DEFAULT_DB_BATCH_SIZE) -> None:
    values = [(
        file_ids_by_sha[row["file_sha256"]], import_date, user_id, row.get("timestamp"),
        row.get("sleep_level"), _jsonb(row.get("raw_json", {})),
    ) for row in rows]
    for batch in _chunks(values, batch_size):
        await conn.executemany(
            """
            INSERT INTO daily_sleep_levels
                (fit_file_id, date, user_id, timestamp, sleep_level, raw_json)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb)
            """,
            batch,
        )


async def _insert_daily_hrv_batches(conn: Any, import_date: date, user_id: int, rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int], batch_size: int = DEFAULT_DB_BATCH_SIZE) -> None:
    values = [(
        file_ids_by_sha[row["file_sha256"]], import_date, user_id, row.get("timestamp"),
        row.get("value_ms"), _jsonb(row.get("raw_json", {})),
    ) for row in rows]
    for batch in _chunks(values, batch_size):
        await conn.executemany(
            """
            INSERT INTO daily_hrv_values
                (fit_file_id, date, user_id, timestamp, value_ms, raw_json)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb)
            """,
            batch,
        )


async def _insert_daily_skin_temp_batches(conn: Any, import_date: date, user_id: int, rows: list[dict[str, Any]], file_ids_by_sha: dict[str, int], batch_size: int = DEFAULT_DB_BATCH_SIZE) -> None:
    values = [(
        file_ids_by_sha[row["file_sha256"]], import_date, user_id, row.get("average_deviation_c"),
        row.get("average_7_day_deviation_c"), row.get("nightly_value_c"), _jsonb(row.get("raw_json", {})),
    ) for row in rows]
    for batch in _chunks(values, batch_size):
        await conn.executemany(
            """
            INSERT INTO daily_skin_temp_overnight
                (fit_file_id, date, user_id, average_deviation_c, average_7_day_deviation_c,
                 nightly_value_c, raw_json)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
            """,
            batch,
        )


async def _upsert_recovery_metrics(conn: Any, import_date: date, user_id: int, summary: dict[str, Any]) -> None:
    if not summary:
        return
    await conn.execute(
        """
        INSERT INTO recovery_metrics
            (date, user_id, stress_avg, stress_max, hrv_overnight_avg, sleep_duration_min,
             sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
             rhr_overnight, steps, distance_km, active_kcal, active_min,
             data_quality, source, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'garmin_fit_daily',now())
        ON CONFLICT (date, user_id) DO UPDATE SET
            stress_avg = COALESCE(EXCLUDED.stress_avg, recovery_metrics.stress_avg),
            stress_max = COALESCE(EXCLUDED.stress_max, recovery_metrics.stress_max),
            hrv_overnight_avg = COALESCE(EXCLUDED.hrv_overnight_avg, recovery_metrics.hrv_overnight_avg),
            sleep_duration_min = COALESCE(EXCLUDED.sleep_duration_min, recovery_metrics.sleep_duration_min),
            sleep_deep_min = COALESCE(EXCLUDED.sleep_deep_min, recovery_metrics.sleep_deep_min),
            sleep_rem_min = COALESCE(EXCLUDED.sleep_rem_min, recovery_metrics.sleep_rem_min),
            sleep_light_min = COALESCE(EXCLUDED.sleep_light_min, recovery_metrics.sleep_light_min),
            sleep_awake_min = COALESCE(EXCLUDED.sleep_awake_min, recovery_metrics.sleep_awake_min),
            rhr_overnight = COALESCE(EXCLUDED.rhr_overnight, recovery_metrics.rhr_overnight),
            steps = COALESCE(EXCLUDED.steps, recovery_metrics.steps),
            distance_km = COALESCE(EXCLUDED.distance_km, recovery_metrics.distance_km),
            active_kcal = COALESCE(EXCLUDED.active_kcal, recovery_metrics.active_kcal),
            active_min = COALESCE(EXCLUDED.active_min, recovery_metrics.active_min),
            data_quality = EXCLUDED.data_quality,
            source = 'garmin_fit_daily',
            updated_at = now()
        """,
        import_date,
        user_id,
        summary.get("stress_avg"),
        summary.get("stress_max"),
        summary.get("hrv_overnight_avg"),
        summary.get("sleep_duration_min"),
        summary.get("sleep_deep_min"),
        summary.get("sleep_rem_min"),
        summary.get("sleep_light_min"),
        summary.get("sleep_awake_min"),
        summary.get("rhr_overnight"),
        summary.get("steps"),
        summary.get("distance_km"),
        summary.get("active_kcal"),
        summary.get("active_min"),
        summary.get("data_quality", "ok"),
    )
