"""WHOOP API v2 integration for Roger (Chief of Sport)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WHOOP_BASE = "https://api.prod.whoop.com/developer"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
ENV_FILE = Path("/home/paluss/docker/.env")
WHOOP_HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
}


@dataclass
class WhoopConfig:
    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    token_expires_at: int = 0
    base_url: str = WHOOP_BASE

    @classmethod
    def from_env(cls) -> "WhoopConfig":
        return cls(
            access_token=os.environ.get("WHOOP_ACCESS_TOKEN", ""),
            refresh_token=os.environ.get("WHOOP_REFRESH_TOKEN", ""),
            client_id=os.environ.get("WHOOP_CLIENT_ID", ""),
            client_secret=os.environ.get("WHOOP_CLIENT_SECRET", ""),
            token_expires_at=int(os.environ.get("WHOOP_TOKEN_EXPIRES_AT", "0") or 0),
        )


@dataclass
class WhoopBundle:
    recoveries: list[dict[str, Any]] = field(default_factory=list)
    sleeps: list[dict[str, Any]] = field(default_factory=list)
    cycles: list[dict[str, Any]] = field(default_factory=list)
    workouts: list[dict[str, Any]] = field(default_factory=list)


def _write_env_value(name: str, value: str, env_file: Path = ENV_FILE) -> None:
    os.environ[name] = value
    if not env_file.exists():
        logger.warning("whoop_sync: .env file not found at %s — %s not persisted", env_file, name)
        return
    text = env_file.read_text()
    replacement = f"{name}={value}"
    if re.search(rf"^{re.escape(name)}=", text, re.MULTILINE):
        text = re.sub(rf"^{re.escape(name)}=.*$", replacement, text, flags=re.MULTILINE)
    else:
        text = text.rstrip() + f"\n{replacement}\n"
    env_file.write_text(text)


class WhoopClient:
    def __init__(
        self,
        config: WhoopConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or WhoopConfig.from_env()
        self.transport = transport

    async def _token(self) -> str:
        if self.config.access_token and time.time() < self.config.token_expires_at - 300:
            return self.config.access_token
        if self.config.access_token and not self.config.refresh_token:
            return self.config.access_token
        return await self._refresh_token()

    async def _refresh_token(self) -> str:
        if not self.config.client_id or not self.config.client_secret or not self.config.refresh_token:
            raise RuntimeError(
                "WHOOP credentials missing: set WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, "
                "WHOOP_REFRESH_TOKEN and WHOOP_ACCESS_TOKEN in /home/paluss/docker/.env"
            )

        async with httpx.AsyncClient(timeout=20.0, transport=self.transport) as client:
            response = await client.post(
                WHOOP_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "refresh_token": self.config.refresh_token,
                },
                headers=WHOOP_HTTP_HEADERS,
            )
            response.raise_for_status()
            data = response.json()

        access_token = data["access_token"]
        refresh_token = data.get("refresh_token", self.config.refresh_token)
        expires_at = int(time.time() + int(data.get("expires_in", 3600)))
        self.config.access_token = access_token
        self.config.refresh_token = refresh_token
        self.config.token_expires_at = expires_at
        _write_env_value("WHOOP_ACCESS_TOKEN", access_token)
        _write_env_value("WHOOP_REFRESH_TOKEN", refresh_token)
        _write_env_value("WHOOP_TOKEN_EXPIRES_AT", str(expires_at))
        return access_token

    async def _get_records(self, path: str, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
        token = await self._token()
        records: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "limit": 25,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=30.0,
            transport=self.transport,
        ) as client:
            while True:
                response = await client.get(
                    path,
                    headers={**WHOOP_HTTP_HEADERS, "Authorization": f"Bearer {token}"},
                    params=params,
                )
                if response.status_code == 401:
                    raise RuntimeError("WHOOP authorization error — token invalid or scopes missing")
                response.raise_for_status()
                payload = response.json()
                page_records = payload.get("records") if isinstance(payload, dict) else payload
                if isinstance(page_records, list):
                    records.extend(row for row in page_records if isinstance(row, dict))
                next_token = payload.get("next_token") or payload.get("nextToken") if isinstance(payload, dict) else None
                if not next_token:
                    break
                params["nextToken"] = next_token
        return records

    async def fetch_bundle(self, *, start: datetime, end: datetime) -> WhoopBundle:
        return WhoopBundle(
            recoveries=await self._get_records("/v2/recovery", start=start, end=end),
            sleeps=await self._get_records("/v2/activity/sleep", start=start, end=end),
            cycles=await self._get_records("/v2/cycle", start=start, end=end),
            workouts=await self._get_records("/v2/activity/workout", start=start, end=end),
        )


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ms_to_min(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value / 60000))


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(round(number)) if number is not None else None


def _date_from_sleep(sleep: dict[str, Any]) -> date | None:
    end_at = _parse_dt(sleep.get("end"))
    if end_at:
        return end_at.date()
    start_at = _parse_dt(sleep.get("start"))
    return start_at.date() if start_at else None


def _duration_min(start_at: datetime | None, end_at: datetime | None) -> float | None:
    if not start_at or not end_at:
        return None
    return round(max(0.0, (end_at - start_at).total_seconds() / 60.0), 1)


def _sleep_summary(sleep: dict[str, Any]) -> dict[str, Any]:
    score = sleep.get("score") or {}
    stages = score.get("stage_summary") or {}
    return {
        "sleep_duration_min": _ms_to_min(stages.get("total_in_bed_time_milli"))
        or _ms_to_min(stages.get("total_sleep_time_milli")),
        "sleep_score": _int(score.get("sleep_performance_percentage")),
        "sleep_deep_min": _ms_to_min(stages.get("total_slow_wave_sleep_time_milli")),
        "sleep_rem_min": _ms_to_min(stages.get("total_rem_sleep_time_milli")),
        "sleep_light_min": _ms_to_min(stages.get("total_light_sleep_time_milli")),
        "sleep_awake_min": _ms_to_min(stages.get("total_awake_time_milli")),
        "respiratory_rate": _num(score.get("respiratory_rate")),
    }


def _sleep_duration_from_stages(summary: dict[str, Any]) -> int | None:
    if summary.get("sleep_duration_min") is not None:
        return summary["sleep_duration_min"]
    parts = [
        summary.get("sleep_deep_min"),
        summary.get("sleep_rem_min"),
        summary.get("sleep_light_min"),
    ]
    values = [int(v) for v in parts if v is not None]
    return sum(values) if values else None


def _cycle_summary(cycle: dict[str, Any]) -> dict[str, Any]:
    score = cycle.get("score") or {}
    return {
        "strain": _num(score.get("strain")),
        "avg_hr": _int(score.get("average_heart_rate")),
        "max_hr": _int(score.get("max_heart_rate")),
        "kilojoule": _num(score.get("kilojoule")),
    }


async def _upsert_whoop_recovery(conn: Any, row: dict[str, Any], user_id: int) -> None:
    score = row.get("score") or {}
    await conn.execute(
        """
        INSERT INTO whoop_recoveries
            (cycle_id, sleep_id, user_id, whoop_user_id, score_state, recovery_score,
             resting_heart_rate, hrv_rmssd_milli, spo2_percentage, skin_temp_celsius,
             raw_json, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,now())
        ON CONFLICT (cycle_id, user_id) DO UPDATE SET
            sleep_id = EXCLUDED.sleep_id,
            whoop_user_id = EXCLUDED.whoop_user_id,
            score_state = EXCLUDED.score_state,
            recovery_score = EXCLUDED.recovery_score,
            resting_heart_rate = EXCLUDED.resting_heart_rate,
            hrv_rmssd_milli = EXCLUDED.hrv_rmssd_milli,
            spo2_percentage = EXCLUDED.spo2_percentage,
            skin_temp_celsius = EXCLUDED.skin_temp_celsius,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """,
        int(row["cycle_id"]),
        str(row.get("sleep_id")) if row.get("sleep_id") is not None else None,
        user_id,
        _int(row.get("user_id")),
        str(row.get("score_state") or ""),
        _int(score.get("recovery_score")),
        _int(score.get("resting_heart_rate")),
        _num(score.get("hrv_rmssd_milli")),
        _num(score.get("spo2_percentage")),
        _num(score.get("skin_temp_celsius")),
        json.dumps(row),
    )


async def _upsert_whoop_sleep(conn: Any, row: dict[str, Any], user_id: int) -> None:
    summary = _sleep_summary(row)
    await conn.execute(
        """
        INSERT INTO whoop_sleeps
            (sleep_id, cycle_id, user_id, whoop_user_id, start_at, end_at,
             timezone_offset, nap, score_state, sleep_duration_min, sleep_score,
             sleep_deep_min, sleep_rem_min, sleep_light_min, sleep_awake_min,
             respiratory_rate, raw_json, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb,now())
        ON CONFLICT (sleep_id, user_id) DO UPDATE SET
            cycle_id = EXCLUDED.cycle_id,
            whoop_user_id = EXCLUDED.whoop_user_id,
            start_at = EXCLUDED.start_at,
            end_at = EXCLUDED.end_at,
            timezone_offset = EXCLUDED.timezone_offset,
            nap = EXCLUDED.nap,
            score_state = EXCLUDED.score_state,
            sleep_duration_min = EXCLUDED.sleep_duration_min,
            sleep_score = EXCLUDED.sleep_score,
            sleep_deep_min = EXCLUDED.sleep_deep_min,
            sleep_rem_min = EXCLUDED.sleep_rem_min,
            sleep_light_min = EXCLUDED.sleep_light_min,
            sleep_awake_min = EXCLUDED.sleep_awake_min,
            respiratory_rate = EXCLUDED.respiratory_rate,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """,
        str(row["id"]),
        _int(row.get("cycle_id")),
        user_id,
        _int(row.get("user_id")),
        _parse_dt(row.get("start")),
        _parse_dt(row.get("end")),
        row.get("timezone_offset"),
        bool(row.get("nap", False)),
        row.get("score_state"),
        _sleep_duration_from_stages(summary),
        summary.get("sleep_score"),
        summary.get("sleep_deep_min"),
        summary.get("sleep_rem_min"),
        summary.get("sleep_light_min"),
        summary.get("sleep_awake_min"),
        summary.get("respiratory_rate"),
        json.dumps(row),
    )


async def _upsert_whoop_cycle(conn: Any, row: dict[str, Any], user_id: int) -> None:
    summary = _cycle_summary(row)
    await conn.execute(
        """
        INSERT INTO whoop_cycles
            (cycle_id, user_id, whoop_user_id, start_at, end_at, timezone_offset,
             score_state, strain, average_heart_rate, max_heart_rate, kilojoule,
             raw_json, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,now())
        ON CONFLICT (cycle_id, user_id) DO UPDATE SET
            whoop_user_id = EXCLUDED.whoop_user_id,
            start_at = EXCLUDED.start_at,
            end_at = EXCLUDED.end_at,
            timezone_offset = EXCLUDED.timezone_offset,
            score_state = EXCLUDED.score_state,
            strain = EXCLUDED.strain,
            average_heart_rate = EXCLUDED.average_heart_rate,
            max_heart_rate = EXCLUDED.max_heart_rate,
            kilojoule = EXCLUDED.kilojoule,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """,
        int(row["id"]),
        user_id,
        _int(row.get("user_id")),
        _parse_dt(row.get("start")),
        _parse_dt(row.get("end")),
        row.get("timezone_offset"),
        row.get("score_state"),
        summary.get("strain"),
        summary.get("avg_hr"),
        summary.get("max_hr"),
        summary.get("kilojoule"),
        json.dumps(row),
    )


async def _upsert_whoop_workout(conn: Any, row: dict[str, Any], user_id: int) -> None:
    score = row.get("score") or {}
    await conn.execute(
        """
        INSERT INTO whoop_workouts
            (workout_id, user_id, whoop_user_id, v1_id, sport_name, start_at, end_at,
             timezone_offset, score_state, strain, average_heart_rate, max_heart_rate,
             kilojoule, distance_meter, altitude_gain_meter, raw_json, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,now())
        ON CONFLICT (workout_id, user_id) DO UPDATE SET
            whoop_user_id = EXCLUDED.whoop_user_id,
            v1_id = EXCLUDED.v1_id,
            sport_name = EXCLUDED.sport_name,
            start_at = EXCLUDED.start_at,
            end_at = EXCLUDED.end_at,
            timezone_offset = EXCLUDED.timezone_offset,
            score_state = EXCLUDED.score_state,
            strain = EXCLUDED.strain,
            average_heart_rate = EXCLUDED.average_heart_rate,
            max_heart_rate = EXCLUDED.max_heart_rate,
            kilojoule = EXCLUDED.kilojoule,
            distance_meter = EXCLUDED.distance_meter,
            altitude_gain_meter = EXCLUDED.altitude_gain_meter,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """,
        str(row["id"]),
        user_id,
        _int(row.get("user_id")),
        _int(row.get("v1_id")),
        row.get("sport_name"),
        _parse_dt(row.get("start")),
        _parse_dt(row.get("end")),
        row.get("timezone_offset"),
        row.get("score_state"),
        _num(score.get("strain")),
        _int(score.get("average_heart_rate")),
        _int(score.get("max_heart_rate")),
        _num(score.get("kilojoule")),
        _num(score.get("distance_meter")),
        _num(score.get("altitude_gain_meter")),
        json.dumps(row),
    )


async def _upsert_observation(
    conn: Any,
    *,
    import_date: date,
    user_id: int,
    recovery: dict[str, Any],
    sleep: dict[str, Any] | None,
    cycle: dict[str, Any] | None,
) -> None:
    recovery_score = recovery.get("score") or {}
    sleep_summary = _sleep_summary(sleep or {})
    cycle_summary = _cycle_summary(cycle or {})
    await conn.execute(
        """
        INSERT INTO daily_recovery_observations
            (date, user_id, source, recovery_score, rhr_overnight, hrv_overnight_avg,
             sleep_duration_min, sleep_deep_min, sleep_rem_min, sleep_light_min,
             sleep_awake_min, data_quality, spo2_percentage, skin_temp_celsius,
             strain, avg_hr, max_hr, raw_json, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::jsonb,now())
        ON CONFLICT (date, user_id, source) DO UPDATE SET
            recovery_score = EXCLUDED.recovery_score,
            rhr_overnight = EXCLUDED.rhr_overnight,
            hrv_overnight_avg = EXCLUDED.hrv_overnight_avg,
            sleep_duration_min = EXCLUDED.sleep_duration_min,
            sleep_deep_min = EXCLUDED.sleep_deep_min,
            sleep_rem_min = EXCLUDED.sleep_rem_min,
            sleep_light_min = EXCLUDED.sleep_light_min,
            sleep_awake_min = EXCLUDED.sleep_awake_min,
            data_quality = EXCLUDED.data_quality,
            spo2_percentage = EXCLUDED.spo2_percentage,
            skin_temp_celsius = EXCLUDED.skin_temp_celsius,
            strain = EXCLUDED.strain,
            avg_hr = EXCLUDED.avg_hr,
            max_hr = EXCLUDED.max_hr,
            raw_json = EXCLUDED.raw_json,
            updated_at = now()
        """,
        import_date,
        user_id,
        "whoop_api_v2",
        _int(recovery_score.get("recovery_score")),
        _int(recovery_score.get("resting_heart_rate")),
        _int(recovery_score.get("hrv_rmssd_milli")),
        _sleep_duration_from_stages(sleep_summary),
        sleep_summary.get("sleep_deep_min"),
        sleep_summary.get("sleep_rem_min"),
        sleep_summary.get("sleep_light_min"),
        sleep_summary.get("sleep_awake_min"),
        "ok" if recovery.get("score_state") == "SCORED" else "incomplete",
        _num(recovery_score.get("spo2_percentage")),
        _num(recovery_score.get("skin_temp_celsius")),
        cycle_summary.get("strain"),
        cycle_summary.get("avg_hr"),
        cycle_summary.get("max_hr"),
        json.dumps({"recovery": recovery, "sleep": sleep or {}, "cycle": cycle or {}}),
    )


async def _insert_activity(conn: Any, workout: dict[str, Any], user_id: int) -> bool:
    workout_id = str(workout.get("id") or "")
    if not workout_id:
        return False
    existing = await conn.fetchrow(
        "SELECT id FROM activities WHERE source = 'whoop' AND user_id = $1 AND raw_json->>'id' = $2",
        user_id,
        workout_id,
    )
    if existing:
        return False

    score = workout.get("score") or {}
    start_at = _parse_dt(workout.get("start"))
    end_at = _parse_dt(workout.get("end"))
    duration_min = _duration_min(start_at, end_at)
    avg_hr = _num(score.get("average_heart_rate"))
    strain = _num(score.get("strain"))
    activity_type = str(workout.get("sport_name") or "workout").lower()
    calories = _int((_num(score.get("kilojoule")) or 0) * 0.239006) if score.get("kilojoule") is not None else None
    distance_km = round(float(score["distance_meter"]) / 1000.0, 3) if score.get("distance_meter") is not None else None
    await conn.fetchrow(
        """
        INSERT INTO activities
            (source, type, date, duration_min, distance_km, avg_hr, max_hr,
             calories, load_score, notes, raw_json, user_id, elevation_gain_m)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13)
        RETURNING id
        """,
        "whoop",
        activity_type,
        start_at.date() if start_at else date.today(),
        duration_min,
        distance_km,
        avg_hr,
        _num(score.get("max_heart_rate")),
        calories,
        strain,
        f"WHOOP workout {workout_id}",
        json.dumps(workout),
        user_id,
        _num(score.get("altitude_gain_meter")),
    )
    return True


async def import_whoop_bundle(conn: Any, bundle: WhoopBundle, *, user_id: int) -> dict[str, Any]:
    sleeps_by_id = {str(row.get("id")): row for row in bundle.sleeps if row.get("id") is not None}
    cycles_by_id = {int(row["id"]): row for row in bundle.cycles if row.get("id") is not None}

    observations = 0
    activities = 0
    async with conn.transaction():
        for row in bundle.recoveries:
            if row.get("cycle_id") is not None:
                await _upsert_whoop_recovery(conn, row, user_id)
        for row in bundle.sleeps:
            if row.get("id") is not None:
                await _upsert_whoop_sleep(conn, row, user_id)
        for row in bundle.cycles:
            if row.get("id") is not None:
                await _upsert_whoop_cycle(conn, row, user_id)

        for recovery in bundle.recoveries:
            cycle_id = recovery.get("cycle_id")
            sleep = sleeps_by_id.get(str(recovery.get("sleep_id"))) if recovery.get("sleep_id") is not None else None
            cycle = cycles_by_id.get(int(cycle_id)) if cycle_id is not None else None
            import_date = _date_from_sleep(sleep or {}) or _parse_dt((cycle or {}).get("end")) or datetime.now(timezone.utc)
            if isinstance(import_date, datetime):
                import_date = import_date.date()
            await _upsert_observation(
                conn,
                import_date=import_date,
                user_id=user_id,
                recovery=recovery,
                sleep=sleep,
                cycle=cycle,
            )
            observations += 1

        for row in bundle.workouts:
            if row.get("id") is None:
                continue
            await _upsert_whoop_workout(conn, row, user_id)
            if await _insert_activity(conn, row, user_id):
                activities += 1

    return {
        "status": "imported",
        "user_id": user_id,
        "raw_recoveries_upserted": len([r for r in bundle.recoveries if r.get("cycle_id") is not None]),
        "raw_sleeps_upserted": len([r for r in bundle.sleeps if r.get("id") is not None]),
        "raw_cycles_upserted": len([r for r in bundle.cycles if r.get("id") is not None]),
        "raw_workouts_upserted": len([r for r in bundle.workouts if r.get("id") is not None]),
        "observations_upserted": observations,
        "activities_inserted": activities,
    }


async def sync_whoop_data(*, date_from: date, date_to: date, user_id: int) -> dict[str, Any]:
    import asyncpg

    start = datetime.combine(date_from, dt_time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, dt_time.max, tzinfo=timezone.utc)
    client = WhoopClient()
    bundle = await client.fetch_bundle(start=start, end=end)

    url = os.environ.get("SPORT_POSTGRES_URL", "")
    if not url:
        raise RuntimeError("SPORT_POSTGRES_URL not configured")

    conn = await asyncpg.connect(url)
    try:
        run_id = None
        try:
            run = await conn.fetchrow(
                """
                INSERT INTO whoop_sync_runs
                    (user_id, date_from, date_to, recoveries_seen, sleeps_seen,
                     cycles_seen, workouts_seen)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING id
                """,
                user_id, date_from, date_to,
                len(bundle.recoveries), len(bundle.sleeps), len(bundle.cycles), len(bundle.workouts),
            )
            run_id = int(run["id"]) if run else None
            result = await import_whoop_bundle(conn, bundle, user_id=user_id)
            await conn.execute(
                "UPDATE whoop_sync_runs SET status = 'completed', completed_at = now() WHERE id = $1",
                run_id,
            )
            result.update({
                "run_id": run_id,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "records_seen": {
                    "recoveries": len(bundle.recoveries),
                    "sleeps": len(bundle.sleeps),
                    "cycles": len(bundle.cycles),
                    "workouts": len(bundle.workouts),
                },
            })
            return result
        except Exception as exc:
            if run_id is not None:
                await conn.execute(
                    "UPDATE whoop_sync_runs SET status = 'failed', completed_at = now(), error_message = $2 WHERE id = $1",
                    run_id,
                    str(exc)[:1000],
                )
            raise
    finally:
        await conn.close()
