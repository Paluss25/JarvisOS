"""Async Postgres helpers for health public schema.

Connection DSN comes from COH_DATABASE_URL (preferred) or DATABASE_URL.
The pool is process-singleton and lazily created on first use.

These helpers are used by the new COH HTTP API (api.py). The legacy
medical pipeline in tools.py keeps using its own SQL paths and is not
affected by this module.
"""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

import asyncpg


_DSN = os.environ.get("COH_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
_pool: asyncpg.Pool | None = None
DEFAULT_MEDICAL_USER_ID = os.environ.get(
    "COH_DEFAULT_MEDICAL_USER_ID",
    "75f9a1ac-e4ca-41cd-8d2b-1f393db7e732",
)


async def pool() -> asyncpg.Pool:
    """Lazily build and return the asyncpg pool."""
    global _pool
    if _pool is None:
        if not _DSN:
            raise RuntimeError(
                "COH_DATABASE_URL/DATABASE_URL not configured — cannot open pool"
            )
        _pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=8)
    return _pool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_abnormal(value, low, high) -> str:
    """Classify a numeric lab value vs its reference range.

    Returns one of: 'normal', 'low', 'high', 'critical'. 'critical' is when the
    value is more than 30% outside the boundary. Falls back to 'normal' when
    inputs are insufficient (missing value or both bounds missing).
    """
    if value is None or low is None or high is None:
        return "normal"
    try:
        v = float(value)
        lo = float(low)
        hi = float(high)
    except (TypeError, ValueError):
        return "normal"
    if v < lo * 0.7 or v > hi * 1.3:
        return "critical"
    if v < lo:
        return "low"
    if v > hi:
        return "high"
    return "normal"


def resolve_medical_user_id(user_id: str) -> str:
    """Map friendly COH aliases to the UUID used by health.public medical tables."""
    normalized = (user_id or "").strip()
    if normalized.lower() in {"", "paluss", "me", "default"}:
        return DEFAULT_MEDICAL_USER_ID
    return normalized


# ---------------------------------------------------------------------------
# Inserts
# ---------------------------------------------------------------------------


async def insert_lab_panel(
    fields: dict, archive_path: str, file_hash: str, user_id: str
) -> UUID:
    """Insert a lab panel + N lab values atomically.

    Idempotent on (user_id, file_hash). When the panel already exists, the
    existing UUID is returned and no values are inserted. When fields supplies
    `abnormal_flag`, that value is used; otherwise it is computed from
    (value, ref_range_low, ref_range_high).
    """
    p = await pool()
    resolved_user_id = resolve_medical_user_id(user_id)
    async with p.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO public.lab_panels
                  (user_id, panel_name, lab_name, physician,
                   collection_date, report_date,
                   archive_path, file_hash, qdrant_collection,
                   extracted_metadata)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (user_id, file_hash) DO NOTHING
                RETURNING id
                """,
                resolved_user_id,
                fields["panel_name"], fields.get("lab_name"),
                fields.get("physician"),
                fields["collection_date"], fields.get("report_date"),
                archive_path, file_hash, "analisi-cliniche",
                json.dumps(fields.get("metadata", {})),
            )
            if row is None:
                existing = await conn.fetchrow(
                    "SELECT id FROM public.lab_panels "
                    "WHERE user_id = $1 AND file_hash = $2",
                    resolved_user_id, file_hash,
                )
                return existing["id"]

            panel_id = row["id"]
            for v in fields.get("values", []):
                ab = v.get("abnormal_flag") or _classify_abnormal(
                    v.get("value"),
                    v.get("ref_range_low"),
                    v.get("ref_range_high"),
                )
                await conn.execute(
                    """
                    INSERT INTO public.lab_values
                      (panel_id, parameter_name, value, value_text, unit,
                       ref_range_low, ref_range_high, abnormal_flag, notes)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    panel_id,
                    v["parameter_name"], v.get("value"), v.get("value_text"),
                    v.get("unit"),
                    v.get("ref_range_low"), v.get("ref_range_high"),
                    ab, v.get("notes"),
                )
            return panel_id


async def insert_medical_report(
    fields: dict, archive_path: str, file_hash: str, user_id: str
) -> UUID:
    """Insert into public.medical_reports. Idempotent on (user_id, file_hash)."""
    p = await pool()
    resolved_user_id = resolve_medical_user_id(user_id)
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO public.medical_reports
              (user_id, report_type, specialist, facility, report_date,
               archive_path, file_hash, qdrant_collection, summary,
               extracted_metadata)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (user_id, file_hash) DO NOTHING
            RETURNING id
            """,
            resolved_user_id,
            fields["report_type"], fields.get("specialist"),
            fields.get("facility"), fields.get("report_date"),
            archive_path, file_hash, "referti-medici",
            fields.get("summary"),
            json.dumps(fields.get("metadata", {})),
        )
        if row is None:
            existing = await conn.fetchrow(
                "SELECT id FROM public.medical_reports "
                "WHERE user_id = $1 AND file_hash = $2",
                resolved_user_id, file_hash,
            )
            return existing["id"]
        return row["id"]


# ---------------------------------------------------------------------------
# Audit + queries
# ---------------------------------------------------------------------------


async def write_audit(
    agent: str,
    action: str,
    document_hash: str | None,
    archive_path: str | None,
    metadata: dict,
) -> None:
    """Append-only insert into public.medical_audit_log."""
    p = await pool()
    async with p.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.medical_audit_log
              (agent, action, document_hash, archive_path, metadata)
            VALUES ($1, $2, $3, $4, $5)
            """,
            agent, action, document_hash, archive_path, json.dumps(metadata),
        )


async def fetch_lab_values(
    parameter_name: str,
    user_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return matching lab values (joined with their panel) for a user.

    `parameter_name` is matched ILIKE so callers can pass exact name or a
    pattern (e.g. 'Glic%'). Optional date bounds and limit.
    """
    p = await pool()
    resolved_user_id = resolve_medical_user_id(user_id)
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.collection_date, v.parameter_name, v.value, v.unit,
                   v.ref_range_low, v.ref_range_high, v.abnormal_flag,
                   p.lab_name
            FROM public.lab_values v
            JOIN public.lab_panels p ON v.panel_id = p.id
            WHERE p.user_id = $1
              AND v.parameter_name ILIKE $2
              AND ($3::date IS NULL OR p.collection_date >= $3::date)
              AND ($4::date IS NULL OR p.collection_date <= $4::date)
            ORDER BY p.collection_date DESC
            LIMIT $5
            """,
            resolved_user_id, parameter_name, from_date, to_date, limit,
        )
        return [dict(r) for r in rows]


async def fetch_lab_anomalies(
    user_id: str, days: int = 90
) -> list[dict[str, Any]]:
    """Return non-normal lab values within the last N days for a user."""
    p = await pool()
    resolved_user_id = resolve_medical_user_id(user_id)
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.collection_date, p.panel_name, v.parameter_name,
                   v.value, v.unit, v.abnormal_flag,
                   v.ref_range_low, v.ref_range_high
            FROM public.lab_values v
            JOIN public.lab_panels p ON v.panel_id = p.id
            WHERE p.user_id = $1
              AND v.abnormal_flag IS NOT NULL
              AND v.abnormal_flag != 'normal'
              AND p.collection_date >= NOW() - make_interval(days => $2)
            ORDER BY p.collection_date DESC,
                     CASE v.abnormal_flag
                       WHEN 'critical' THEN 0
                       WHEN 'high'     THEN 1
                       WHEN 'low'      THEN 2
                       ELSE 3
                     END
            """,
            resolved_user_id, days,
        )
        return [dict(r) for r in rows]


async def fetch_medical_reports(
    user_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
    report_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return medical reports for a user, optionally filtered by date and type."""
    p = await pool()
    resolved_user_id = resolve_medical_user_id(user_id)
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, report_type, specialist, facility, report_date,
                   archive_path, summary
            FROM public.medical_reports
            WHERE user_id = $1
              AND ($2::date IS NULL OR report_date >= $2::date)
              AND ($3::date IS NULL OR report_date <= $3::date)
              AND ($4::text IS NULL OR report_type = $4)
            ORDER BY report_date DESC NULLS LAST
            LIMIT $5
            """,
            resolved_user_id, from_date, to_date, report_type, limit,
        )
        return [dict(r) for r in rows]
