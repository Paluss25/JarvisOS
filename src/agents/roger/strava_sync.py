"""Strava API integration for Roger (Chief of Sport).

Handles:
- Automatic token refresh (writes new tokens back to .env)
- Activity summary download via /activities/{id}
- Raw streams download via /activities/{id}/streams
- INSERT into sport_metrics.activities (PostgreSQL)
- Parquet export to workspace/knowledge/strava_data/
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

STRAVA_BASE = "https://www.strava.com/api/v3"
ENV_FILE = Path("/home/paluss/docker/.env")

# Strava sport type → internal activity type
_TYPE_MAP: dict[str, str] = {
    "Run": "run",
    "Ride": "bike",
    "VirtualRide": "bike",
    "Swim": "swim",
    "Walk": "walk",
    "Hike": "hike",
    "WeightTraining": "hiit",
    "Workout": "tennis",
    "Tennis": "tennis",
    "Crossfit": "hiit",
    "Rowing": "bike",
    "EBikeRide": "bike",
}

# Streams to request from Strava
_STREAM_KEYS = (
    "time,latlng,altitude,heartrate,cadence,"
    "velocity_smooth,watts,moving,grade_smooth"
)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _read_env_tokens() -> tuple[str, str, int]:
    """Read current Strava tokens from os.environ (loaded from .env at startup)."""
    access_token = os.environ.get("STRAVA_ACCESS_TOKEN", "")
    refresh_token = os.environ.get("STRAVA_REFRESH_TOKEN", "")
    expires_at = int(os.environ.get("STRAVA_TOKEN_EXPIRES_AT", "0"))
    return access_token, refresh_token, expires_at


def _write_env_tokens(access_token: str, refresh_token: str, expires_at: int) -> None:
    """Persist refreshed tokens into os.environ and back to .env file."""
    os.environ["STRAVA_ACCESS_TOKEN"] = access_token
    os.environ["STRAVA_REFRESH_TOKEN"] = refresh_token
    os.environ["STRAVA_TOKEN_EXPIRES_AT"] = str(expires_at)

    if not ENV_FILE.exists():
        logger.warning("strava_sync: .env file not found at %s — tokens not persisted to disk", ENV_FILE)
        return

    text = ENV_FILE.read_text()
    text = re.sub(r"^STRAVA_ACCESS_TOKEN=.*$", f"STRAVA_ACCESS_TOKEN={access_token}", text, flags=re.MULTILINE)
    text = re.sub(r"^STRAVA_REFRESH_TOKEN=.*$", f"STRAVA_REFRESH_TOKEN={refresh_token}", text, flags=re.MULTILINE)

    if re.search(r"^STRAVA_TOKEN_EXPIRES_AT=", text, re.MULTILINE):
        text = re.sub(
            r"^STRAVA_TOKEN_EXPIRES_AT=.*$",
            f"STRAVA_TOKEN_EXPIRES_AT={expires_at}",
            text,
            flags=re.MULTILINE,
        )
    else:
        text = text.rstrip() + f"\nSTRAVA_TOKEN_EXPIRES_AT={expires_at}\n"

    ENV_FILE.write_text(text)
    logger.info("strava_sync: tokens refreshed and persisted to .env")


async def _get_valid_token() -> str:
    """Return a valid access token, refreshing automatically if expired."""
    access_token, refresh_token, expires_at = _read_env_tokens()

    # 5-minute safety buffer
    if access_token and time.time() < expires_at - 300:
        return access_token

    client_id = os.environ.get("STRAVA_CLIENT_ID", "")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "")

    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError(
            "Strava credentials missing: set STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, "
            "STRAVA_REFRESH_TOKEN in .env"
        )

    logger.info("strava_sync: access token expired — refreshing via refresh_token")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _write_env_tokens(data["access_token"], data["refresh_token"], data["expires_at"])
    return data["access_token"]


# ---------------------------------------------------------------------------
# Strava API calls
# ---------------------------------------------------------------------------

async def list_recent_activities(n: int = 5, token: str | None = None) -> list[dict]:
    """
    Fetch the N most recent activities from Strava (/athlete/activities).
    Returns a compact list with id, name, type, date, duration_min, distance_km, avg_hr.
    """
    if token is None:
        token = await _get_valid_token()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{STRAVA_BASE}/athlete/activities",
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": min(n, 50), "page": 1},
        )
        if resp.status_code == 401:
            raise RuntimeError("Strava authorization error — token may be invalid")
        resp.raise_for_status()
        activities = resp.json()

    result = []
    for a in activities[:n]:
        start_dt = datetime.fromisoformat(a.get("start_date_local", "").replace("Z", ""))
        result.append({
            "activity_id":   a["id"],
            "name":          a.get("name", ""),
            "type":          _TYPE_MAP.get(a.get("sport_type", a.get("type", "")), a.get("sport_type", "")),
            "date":          start_dt.strftime("%Y-%m-%d"),
            "duration_min":  round(a.get("moving_time", 0) / 60, 1),
            "distance_km":   round(a.get("distance", 0) / 1000, 2) if a.get("distance") else None,
            "avg_hr":        a.get("average_heartrate"),
            "max_hr":        a.get("max_heartrate"),
            "calories":      a.get("calories"),
            "elevation_m":   a.get("total_elevation_gain"),
            "suffer_score":  a.get("suffer_score"),
        })
    return result


async def _fetch_activity_summary(activity_id: int, token: str) -> dict:
    """Fetch full activity summary from Strava."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{STRAVA_BASE}/activities/{activity_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            raise ValueError(f"Activity {activity_id} not found on Strava")
        if resp.status_code == 401:
            raise RuntimeError("Strava authorization error — token may be invalid")
        resp.raise_for_status()
        return resp.json()


async def _fetch_streams(activity_id: int, token: str) -> dict:
    """Fetch activity streams (time-series sensor data) from Strava."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{STRAVA_BASE}/activities/{activity_id}/streams",
            headers={"Authorization": f"Bearer {token}"},
            params={"keys": _STREAM_KEYS, "key_by_type": "true"},
        )
        if resp.status_code == 200:
            return resp.json()
        # Streams may not be available for all activities (e.g. manual entries)
        logger.warning("strava_sync: streams not available for %d — status %d", activity_id, resp.status_code)
        return {}


# ---------------------------------------------------------------------------
# PostgreSQL save
# ---------------------------------------------------------------------------

async def _save_to_postgres(summary: dict, user_id: int) -> tuple[int | None, str]:
    """
    Insert activity into sport_metrics.activities.
    Returns (db_id, status) where status is 'inserted' or 'already_exists'.
    """
    from agents.roger.tools import _pg_execute

    strava_activity_id = int(summary["id"])

    # Idempotency check via indexed BIGINT column (fast, no full-table scan)
    existing = await _pg_execute(
        "SELECT id FROM activities WHERE strava_activity_id = $1 AND user_id = $2",
        [strava_activity_id, user_id],
    )
    if existing:
        return existing[0]["id"], "already_exists"

    # Map fields
    start_dt = datetime.fromisoformat(summary["start_date_local"].replace("Z", ""))
    activity_date = start_dt.date()
    activity_type = _TYPE_MAP.get(summary.get("type", ""), summary.get("type", "").lower())
    duration_min = round(summary.get("moving_time", 0) / 60, 1)
    distance_km = round(summary.get("distance", 0) / 1000, 3) if summary.get("distance") else None
    avg_hr = summary.get("average_heartrate")
    max_hr = summary.get("max_heartrate")
    calories = summary.get("calories")
    elevation_gain_m = summary.get("total_elevation_gain")
    avg_cadence = summary.get("average_cadence")
    suffer_score = summary.get("suffer_score")

    # Load score: duration × normalized HR factor (baseline 150 bpm)
    hr_for_load = avg_hr if avg_hr else 120
    load_score = round(duration_min * (hr_for_load / 150), 1)

    result = await _pg_execute(
        """
        INSERT INTO activities
            (source, type, date, duration_min, distance_km, avg_hr, max_hr,
             calories, load_score, notes, raw_json, user_id,
             strava_activity_id, elevation_gain_m, avg_cadence, suffer_score)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        RETURNING id
        """,
        [
            "strava",
            activity_type,
            activity_date,
            duration_min,
            distance_km,
            avg_hr,
            max_hr,
            calories,
            load_score,
            summary.get("name", ""),
            json.dumps(summary),
            user_id,
            strava_activity_id,
            elevation_gain_m,
            avg_cadence,
            suffer_score,
        ],
    )

    db_id = result[0]["id"] if result else None
    return db_id, "inserted"


# ---------------------------------------------------------------------------
# Parquet save
# ---------------------------------------------------------------------------

def _save_to_parquet(
    activity_id: int,
    summary: dict,
    streams: dict,
    workspace_path: Path,
) -> Path:
    """
    Save activity summary + streams to Parquet.
    One row per activity; streams stored as JSON-serialized arrays.
    Output: workspace/knowledge/strava_data/<activity_id>.parquet
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    out_dir = workspace_path / "knowledge" / "strava_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{activity_id}.parquet"

    start_dt = datetime.fromisoformat(summary["start_date_local"].replace("Z", ""))

    record: dict[str, list[Any]] = {
        "activity_id":       [activity_id],
        "strava_name":       [summary.get("name", "")],
        "type":              [summary.get("type", "")],
        "date":              [start_dt.strftime("%Y-%m-%d")],
        "start_datetime":    [summary.get("start_date_local", "")],
        "duration_s":        [int(summary.get("moving_time", 0))],
        "elapsed_s":         [int(summary.get("elapsed_time", 0))],
        "distance_m":        [float(summary.get("distance", 0.0))],
        "elevation_gain_m":  [float(summary.get("total_elevation_gain", 0.0))],
        "avg_hr":            [summary.get("average_heartrate")],
        "max_hr":            [summary.get("max_heartrate")],
        "avg_speed_ms":      [float(summary.get("average_speed", 0.0))],
        "max_speed_ms":      [float(summary.get("max_speed", 0.0))],
        "avg_cadence":       [summary.get("average_cadence")],
        "avg_watts":         [summary.get("average_watts")],
        "kilojoules":        [summary.get("kilojoules")],
        "calories":          [summary.get("calories")],
        "kudos_count":       [int(summary.get("kudos_count", 0))],
        "athlete_id":        [summary.get("athlete", {}).get("id")],
        "gear_id":           [summary.get("gear_id")],
        "device_name":       [summary.get("device_name")],
        "trainer":           [bool(summary.get("trainer", False))],
        "commute":           [bool(summary.get("commute", False))],
    }

    # Streams: stored as JSON arrays (one element per data point)
    for key, stream_obj in (streams or {}).items():
        if isinstance(stream_obj, dict) and "data" in stream_obj:
            record[f"stream_{key}"] = [json.dumps(stream_obj["data"])]
        else:
            record[f"stream_{key}"] = [None]

    table = pa.Table.from_pydict(record)
    pq.write_table(table, str(out_file), compression="snappy")
    logger.info("strava_sync: Parquet saved → %s", out_file)
    return out_file


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def fetch_and_store_activity(
    activity_id: int,
    user_id: int | None = None,
    workspace_path: Path | None = None,
) -> dict:
    """
    Full pipeline: token refresh → Strava API → PostgreSQL → Parquet.

    Returns a summary dict with all results for the agent to report.
    """
    if user_id is None:
        user_id = int(os.environ.get("SPORT_USER_ID", "1"))
    if workspace_path is None:
        workspace_path = Path(os.environ.get("ROGER_WORKSPACE", "/app/workspace/roger"))

    # 1. Ensure valid token
    token = await _get_valid_token()

    # 2. Fetch from Strava
    summary = await _fetch_activity_summary(activity_id, token)
    streams = await _fetch_streams(activity_id, token)

    # 3. PostgreSQL
    db_id, db_status = await _save_to_postgres(summary, user_id)

    # 4. Parquet
    parquet_path: str
    try:
        p = _save_to_parquet(activity_id, summary, streams, workspace_path)
        parquet_path = str(p)
    except Exception as exc:
        logger.error("strava_sync: Parquet save failed — %s", exc)
        parquet_path = f"error: {exc}"

    # Computed fields for the summary
    start_dt = datetime.fromisoformat(summary["start_date_local"].replace("Z", ""))
    duration_min = round(summary.get("moving_time", 0) / 60, 1)
    distance_km = round(summary.get("distance", 0) / 1000, 2) if summary.get("distance") else None
    avg_hr = summary.get("average_heartrate")
    hr_for_load = avg_hr if avg_hr else 120
    load_score = round(duration_min * (hr_for_load / 150), 1)

    return {
        "activity_id":       activity_id,
        "db_id":             db_id,
        "db_status":         db_status,
        "type":              _TYPE_MAP.get(summary.get("type", ""), summary.get("type", "")),
        "date":              start_dt.strftime("%Y-%m-%d"),
        "name":              summary.get("name"),
        "duration_min":      duration_min,
        "distance_km":       distance_km,
        "avg_hr":            avg_hr,
        "max_hr":            summary.get("max_heartrate"),
        "calories":          summary.get("calories"),
        "elevation_gain_m":  summary.get("total_elevation_gain"),
        "avg_cadence":       summary.get("average_cadence"),
        "suffer_score":      summary.get("suffer_score"),
        "load_score":        load_score,
        "streams_available": list(streams.keys()) if isinstance(streams, dict) else [],
        "parquet_path":      parquet_path,
    }
