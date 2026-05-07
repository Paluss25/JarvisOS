"""Async Postgres helpers for the human_res database.

Connection DSN comes from CHRO_DATABASE_URL (preferred) or DATABASE_URL.
The pool is process-singleton and lazily created on first use.

These helpers are used by the new CHRO HTTP API (api.py). The legacy
Telegram-driven CHRO pipeline (tools.py) keeps using its own SQL paths
and is not affected by this module.
"""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

import asyncpg


_DSN = os.environ.get("CHRO_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
_pool: asyncpg.Pool | None = None
DEFAULT_HR_USER_ID = os.environ.get(
    "CHRO_DEFAULT_HR_USER_ID",
    "75f9a1ac-e4ca-41cd-8d2b-1f393db7e732",
)


async def pool() -> asyncpg.Pool:
    """Lazily build and return the asyncpg pool."""
    global _pool
    if _pool is None:
        if not _DSN:
            raise RuntimeError(
                "CHRO_DATABASE_URL/DATABASE_URL not configured — cannot open pool"
            )
        _pool = await asyncpg.create_pool(_DSN, min_size=1, max_size=8)
    return _pool


def resolve_hr_user_id(user_id: str) -> str:
    """Map friendly CHRO aliases to the UUID used by human_res payslip rows."""
    normalized = (user_id or "").strip()
    if normalized.lower() in {"", "paluss", "me", "default"}:
        return DEFAULT_HR_USER_ID
    return normalized


# ---------------------------------------------------------------------------
# Inserts
# ---------------------------------------------------------------------------


async def insert_payslip(
    fields: dict, archive_path: str, file_hash: str, user_id: str
) -> UUID:
    """Insert a payslip + items into the migrated payslips schema.

    Schema (post-migration 002): user_id (UUID), document_id (UUID, optional),
    month, year, employer, employee_name, employee_code, gross_amount,
    net_amount, tax_amount, contribution_amount, status (payslip_status enum,
    default 'draft'), extraction_confidence, extraction_metadata, notes,
    plus archive_path and file_hash added by migration 002.

    Idempotent on (user_id, file_hash).
    """
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO payslips
              (user_id, month, year, employer, employee_name, employee_code,
               gross_amount, net_amount, tax_amount, contribution_amount,
               status, extraction_confidence, extraction_metadata, notes,
               archive_path, file_hash)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT (user_id, file_hash) DO NOTHING
            RETURNING id
            """,
            resolved_user_id,
            fields["month"], fields["year"],
            fields.get("employer"), fields.get("employee_name"), fields.get("employee_code"),
            fields.get("gross_amount"), fields["net_amount"],
            fields.get("tax_amount"), fields.get("contribution_amount"),
            fields.get("status", "draft"),
            fields.get("extraction_confidence"),
            json.dumps(fields.get("extraction_metadata", {})),
            fields.get("notes"),
            archive_path, file_hash,
        )
        if row is None:
            existing = await conn.fetchrow(
                "SELECT id FROM payslips WHERE user_id = $1 AND file_hash = $2",
                resolved_user_id, file_hash,
            )
            return existing["id"]

        payslip_id = row["id"]

        # payslip_items uses the existing columns: item_type, item_category,
        # description, amount, quantity, rate, metadata.
        for item in fields.get("items", []):
            await conn.execute(
                """
                INSERT INTO payslip_items
                  (payslip_id, item_type, item_category, description, amount,
                   quantity, rate, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                payslip_id,
                item["item_type"], item["item_category"],
                item["description"], item["amount"],
                item.get("quantity", 1.0), item.get("rate"),
                json.dumps(item.get("metadata", {})),
            )
        return payslip_id


async def insert_expense(
    fields: dict, archive_path: str, file_hash: str, user_id: str
) -> UUID:
    """Insert into expense_items. Idempotent on (user_id, file_hash)."""
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO expense_items
              (user_id, expense_date, category, amount_eur,
               reimbursement_status, employer_ref, notes,
               archive_path, file_hash)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (user_id, file_hash) DO NOTHING
            RETURNING id
            """,
            resolved_user_id,
            fields["expense_date"], fields.get("category"),
            fields["amount_eur"], fields.get("reimbursement_status", "pending"),
            fields.get("employer_ref"), fields.get("notes"),
            archive_path, file_hash,
        )
        if row is None:
            existing = await conn.fetchrow(
                "SELECT id FROM expense_items WHERE user_id = $1 AND file_hash = $2",
                resolved_user_id, file_hash,
            )
            return existing["id"]
        return row["id"]


async def insert_contract(
    fields: dict, archive_path: str, file_hash: str, user_id: str
) -> UUID:
    """Insert into contracts. Idempotent on (user_id, file_hash)."""
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO contracts
              (user_id, contract_type, employer, role,
               start_date, end_date, gross_yearly,
               archive_path, file_hash, extracted_metadata)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (user_id, file_hash) DO NOTHING
            RETURNING id
            """,
            resolved_user_id,
            fields.get("contract_type"), fields.get("employer"),
            fields.get("role"), fields.get("start_date"), fields.get("end_date"),
            fields.get("gross_yearly"),
            archive_path, file_hash,
            json.dumps(fields.get("metadata", {})),
        )
        if row is None:
            existing = await conn.fetchrow(
                "SELECT id FROM contracts WHERE user_id = $1 AND file_hash = $2",
                resolved_user_id, file_hash,
            )
            return existing["id"]
        return row["id"]


async def insert_leonardo_doc(
    fields: dict, archive_path: str, file_hash: str, user_id: str
) -> UUID:
    """Insert into leonardo_docs. Idempotent on (user_id, file_hash)."""
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leonardo_docs
              (user_id, title, doc_date, tags,
               archive_path, file_hash, qdrant_collection)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (user_id, file_hash) DO NOTHING
            RETURNING id
            """,
            resolved_user_id,
            fields.get("title"), fields.get("doc_date"),
            fields.get("tags", []),
            archive_path, file_hash, "documentazione-leonardo",
        )
        if row is None:
            existing = await conn.fetchrow(
                "SELECT id FROM leonardo_docs WHERE user_id = $1 AND file_hash = $2",
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
    """Append-only insert into hr_audit_log."""
    p = await pool()
    async with p.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO hr_audit_log
              (agent, action, document_hash, archive_path, metadata)
            VALUES ($1, $2, $3, $4, $5)
            """,
            agent, action, document_hash, archive_path, json.dumps(metadata),
        )


async def fetch_recent_payslips(user_id: str, limit: int = 6) -> list[dict[str, Any]]:
    """Return the most recent N payslips for a user, newest first."""
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, month, year, employer, employee_name,
                   gross_amount, net_amount, tax_amount, contribution_amount,
                   status, archive_path
            FROM payslips
            WHERE user_id = $1
            ORDER BY year DESC, month DESC
            LIMIT $2
            """,
            resolved_user_id, limit,
        )
        return [dict(r) for r in rows]


async def fetch_recent_expenses(
    user_id: str, limit: int = 24
) -> list[dict[str, Any]]:
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, expense_date, category, amount_eur,
                   reimbursement_status, employer_ref, notes, archive_path
            FROM expense_items
            WHERE user_id = $1
            ORDER BY expense_date DESC
            LIMIT $2
            """,
            resolved_user_id, limit,
        )
        return [dict(r) for r in rows]


async def fetch_recent_contracts(
    user_id: str, limit: int = 24
) -> list[dict[str, Any]]:
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, contract_type, employer, role,
                   start_date, end_date, gross_yearly, archive_path
            FROM contracts
            WHERE user_id = $1
            ORDER BY start_date DESC NULLS LAST
            LIMIT $2
            """,
            resolved_user_id, limit,
        )
        return [dict(r) for r in rows]


async def fetch_recent_leonardo_docs(
    user_id: str, limit: int = 24
) -> list[dict[str, Any]]:
    p = await pool()
    resolved_user_id = resolve_hr_user_id(user_id)
    async with p.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, doc_date, tags, archive_path
            FROM leonardo_docs
            WHERE user_id = $1
            ORDER BY doc_date DESC NULLS LAST
            LIMIT $2
            """,
            resolved_user_id, limit,
        )
        return [dict(r) for r in rows]
