"""FastAPI router for /chro/* endpoints.

Mounted into the CHRO agent's FastAPI app (port 8004) by run.py.

Pipeline:
    1. Receive PDF + collection.
    2. Forward to memory-box (/ingest/pdf) for archive + redact (hr profile)
       + embed.
    3. LLM-extract structured fields from the redacted text.
    4. INSERT into the matching chro.* table (idempotent on file_hash).
    5. Detect anomalies and write hr_audit_log.

The LLM call is performed via the local `claude` CLI in subprocess form
(same pattern used by agent_runner.memory.pipeline.extractor) — no
agent_runner.llm wrapper exists in this codebase.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import date
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from agents.chro import anomalies, db, extractor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chro", tags=["chro"])


MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://memory-box:8000")

DEFAULT_ARCHIVE_DIRS = {
    "cedolini": "/mnt/Brains/HR/archive/payslips",
    "note-spese": "/mnt/Brains/HR/archive/expenses",
    "contratti": "/mnt/Brains/HR/archive/contracts",
    "documentazione-leonardo": "/mnt/Brains/HR/archive/leonardo-docs",
}

COLLECTION_TO_DOCTYPE = {
    "cedolini": "payslip",
    "note-spese": "expense_report",
    "contratti": "contract",
    "documentazione-leonardo": "leonardo_doc",
}


# ---------------------------------------------------------------------------
# LLM binding
# ---------------------------------------------------------------------------

async def _llm_call(prompt: str) -> str:
    """Run extraction through the local `claude` CLI (OAuth, no API cost).

    Mirrors the subprocess pattern used by
    agent_runner.memory.pipeline.extractor._extract_claude_cli. We pick the
    fallback model env (haiku-class) — the schema-bounded JSON extraction
    does not need the agent-class model.
    """
    model = (
        os.environ.get("CHRO_EXTRACTOR_MODEL")
        or os.environ.get("CLAUDE_FALLBACK_MODEL")
        or "claude-haiku-4-5-20251001"
    )
    proc = await asyncio.create_subprocess_exec(
        "claude", "--model", model, "-p", prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="LLM extraction timed out")
    if proc.returncode != 0:
        logger.warning("claude CLI failed: %s", stderr.decode()[:500])
        raise HTTPException(
            status_code=502,
            detail=f"LLM extraction failed: {stderr.decode()[:200]}",
        )
    return stdout.decode()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/ingest")
async def chro_ingest(
    file: UploadFile = File(...),
    collection: str = Form(...),
    user_id: str = Form(...),
    archive_dir: str | None = Form(None),
    redact: bool = Form(True),
):
    if collection not in COLLECTION_TO_DOCTYPE:
        raise HTTPException(
            status_code=422, detail=f"Unknown collection: {collection}"
        )

    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    if archive_dir is None:
        year = date.today().year
        if collection in ("contratti", "documentazione-leonardo"):
            archive_dir = DEFAULT_ARCHIVE_DIRS[collection]
        else:
            archive_dir = f"{DEFAULT_ARCHIVE_DIRS[collection]}/{year}"

    # Step 1: data-plane call
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{MEMORY_BOX_URL}/ingest/pdf",
                files={
                    "file": (
                        file.filename,
                        content,
                        file.content_type or "application/pdf",
                    ),
                },
                data={
                    "collection": collection,
                    "user": user_id,
                    "redact": "true" if redact else "false",
                    "redact_profile": "hr",
                    "archive_original": "true",
                    "archive_dir": archive_dir,
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"memory-box unreachable: {exc}"
        ) from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"memory-box error: {resp.text}"
        )
    mb = resp.json()

    redacted_text = mb.get("redacted_text", "")
    archive_path = mb.get("archive_path")
    doc_type = COLLECTION_TO_DOCTYPE[collection]

    # Step 2: extract structured fields
    try:
        fields = await extractor.extract_fields(redacted_text, doc_type, _llm_call)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CHRO extraction failed for %s", file.filename)
        try:
            await db.write_audit(
                "chro", "ingest_failed", file_hash, archive_path,
                {"doc_type": doc_type, "error": str(exc)},
            )
        except Exception:  # don't let audit failure mask the real error
            logger.exception("audit write failed")
        raise HTTPException(
            status_code=500, detail=f"extraction failed: {exc}"
        ) from exc

    # Step 3: insert
    document_id: Any
    detected: list[dict] = []
    if doc_type == "payslip":
        prior = await db.fetch_recent_payslips(user_id, limit=2)
        document_id = await db.insert_payslip(
            fields, archive_path, file_hash, user_id
        )
        detected = anomalies.detect_payslip_anomalies(fields, prior)
    elif doc_type == "expense_report":
        document_id = await db.insert_expense(
            fields, archive_path, file_hash, user_id
        )
        detected = anomalies.detect_expense_anomalies(fields)
    elif doc_type == "contract":
        document_id = await db.insert_contract(
            fields, archive_path, file_hash, user_id
        )
    elif doc_type == "leonardo_doc":
        document_id = await db.insert_leonardo_doc(
            fields, archive_path, file_hash, user_id
        )
    else:
        raise HTTPException(
            status_code=500, detail=f"Unhandled doc_type: {doc_type}"
        )

    # Step 4: audit
    await db.write_audit("chro", "ingest", file_hash, archive_path, {
        "doc_type": doc_type,
        "document_id": str(document_id),
        "anomalies": detected,
        "chunks_written": mb.get("chunks_written"),
        "redaction_stats": mb.get("redaction_stats"),
    })

    return {
        "status": "ok",
        "document_id": str(document_id),
        "doc_type": doc_type,
        "archive_path": archive_path,
        "chunks_written": mb.get("chunks_written"),
        "anomalies": detected,
        "redaction_stats": mb.get("redaction_stats"),
    }


# --- List endpoints --------------------------------------------------------

@router.get("/payslips")
async def list_payslips(
    user_id: str = Query(...), limit: int = Query(24, ge=1, le=240)
):
    rows = await db.fetch_recent_payslips(user_id, limit=limit)
    return _serialize_rows(rows)


@router.get("/expenses")
async def list_expenses(
    user_id: str = Query(...), limit: int = Query(24, ge=1, le=240)
):
    rows = await db.fetch_recent_expenses(user_id, limit=limit)
    return _serialize_rows(rows)


@router.get("/contracts")
async def list_contracts(
    user_id: str = Query(...), limit: int = Query(24, ge=1, le=240)
):
    rows = await db.fetch_recent_contracts(user_id, limit=limit)
    return _serialize_rows(rows)


@router.get("/leonardo")
async def list_leonardo_docs(
    user_id: str = Query(...), limit: int = Query(24, ge=1, le=240)
):
    rows = await db.fetch_recent_leonardo_docs(user_id, limit=limit)
    return _serialize_rows(rows)


# --- Health ---------------------------------------------------------------

@router.get("/health")
async def health():
    try:
        p = await db.pool()
        async with p.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)}
    return {"status": "ok"}


# --- Helpers --------------------------------------------------------------

def _serialize_rows(rows: list[dict]) -> list[dict]:
    """Coerce Decimal/UUID/date types to JSON-friendly forms."""
    out: list[dict] = []
    for row in rows:
        item: dict[str, Any] = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            else:
                try:
                    json.dumps(v)
                    item[k] = v
                except TypeError:
                    item[k] = str(v)
        out.append(item)
    return out
