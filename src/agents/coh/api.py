"""FastAPI router for /coh/* endpoints.

Mounted into the DrHouse (COH) agent's FastAPI app (port 8006) by run.py.

Pipeline:
    1. Receive PDF + collection (analisi-cliniche or referti-medici).
    2. Forward to memory-box (/ingest/pdf) for archive + redact (medical
       profile) + embed.
    3. LLM-extract structured fields from the redacted text.
    4. INSERT into the matching public medical table (idempotent on file_hash).
    5. Write public.medical_audit_log.

The LLM call is performed via the local `claude` CLI in subprocess form
(same pattern used by agents.human_res.api and
agent_runner.memory.pipeline.extractor) — no agent_runner.llm wrapper
exists in this codebase.
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

from agents.coh import db, extractor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coh", tags=["coh"])


MEMORY_BOX_URL = os.environ.get("MEMORY_BOX_URL", "http://memory-box:8000")

DEFAULT_ARCHIVE_DIRS = {
    "analisi-cliniche": "/mnt/Brains/Medical/analisi-cliniche",
    "referti-medici":   "/mnt/Brains/Medical/referti-medici",
}


# ---------------------------------------------------------------------------
# LLM binding
# ---------------------------------------------------------------------------


async def _llm_call(prompt: str) -> str:
    """Run extraction through the local `claude` CLI (OAuth, no API cost).

    Mirrors the subprocess pattern used by agents.human_res.api._llm_call. The
    schema-bounded JSON extraction does not need the agent-class model, so
    we pick the haiku-class fallback by default. Override via
    COH_EXTRACTOR_MODEL → CLAUDE_FALLBACK_MODEL → claude-haiku-4-5-20251001.
    """
    model = (
        os.environ.get("COH_EXTRACTOR_MODEL")
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
async def coh_ingest(
    file: UploadFile = File(...),
    collection: str = Form(...),
    user_id: str = Form(...),
    archive_dir: str | None = Form(None),
    redact: bool = Form(True),
):
    if collection not in DEFAULT_ARCHIVE_DIRS:
        raise HTTPException(
            status_code=422, detail=f"Unknown collection: {collection}"
        )

    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    if archive_dir is None:
        year = date.today().year
        archive_dir = f"{DEFAULT_ARCHIVE_DIRS[collection]}/{year}"

    # Step 1: data-plane call to memory-box
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
                    "redact_profile": "medical",
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

    # Step 2 + 3: extract structured fields, insert into public medical tables.
    document_id: Any
    if collection == "analisi-cliniche":
        try:
            fields = await extractor.extract_lab_panel(redacted_text, _llm_call)
            document_id = await db.insert_lab_panel(
                fields, archive_path, file_hash, user_id
            )
            doc_type = "lab_panel"
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("COH lab extraction failed for %s", file.filename)
            try:
                await db.write_audit(
                    "coh", "ingest_failed", file_hash, archive_path,
                    {"collection": collection, "error": str(exc)},
                )
            except Exception:  # don't let audit failure mask the real error
                logger.exception("audit write failed")
            raise HTTPException(
                status_code=500, detail=f"lab extraction failed: {exc}"
            ) from exc
    else:  # referti-medici
        try:
            fields = await extractor.extract_medical_report(
                redacted_text, _llm_call
            )
            document_id = await db.insert_medical_report(
                fields, archive_path, file_hash, user_id
            )
            doc_type = fields.get("report_type", "other")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("COH report extraction failed for %s", file.filename)
            try:
                await db.write_audit(
                    "coh", "ingest_failed", file_hash, archive_path,
                    {"collection": collection, "error": str(exc)},
                )
            except Exception:
                logger.exception("audit write failed")
            raise HTTPException(
                status_code=500, detail=f"report extraction failed: {exc}"
            ) from exc

    # Step 4: audit
    await db.write_audit("coh", "ingest", file_hash, archive_path, {
        "collection": collection,
        "doc_type": doc_type,
        "document_id": str(document_id),
        "chunks_written": mb.get("chunks_written"),
        "redaction_stats": mb.get("redaction_stats"),
    })

    return {
        "status": "ok",
        "document_id": str(document_id),
        "doc_type": doc_type,
        "archive_path": archive_path,
        "chunks_written": mb.get("chunks_written"),
        "redaction_stats": mb.get("redaction_stats"),
    }


# --- Read endpoints --------------------------------------------------------


@router.get("/lab-values")
async def list_lab_values(
    parameter_name: str = Query(...),
    user_id: str = Query(...),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    rows = await db.fetch_lab_values(
        parameter_name, user_id, from_date, to_date, limit
    )
    return _serialize_rows(rows)


@router.get("/lab-anomalies")
async def list_lab_anomalies(
    user_id: str = Query(...), days: int = Query(90, ge=1, le=3650)
):
    rows = await db.fetch_lab_anomalies(user_id, days)
    return _serialize_rows(rows)


@router.get("/medical-reports")
async def list_medical_reports(
    user_id: str = Query(...),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    report_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    rows = await db.fetch_medical_reports(
        user_id, from_date, to_date, report_type, limit
    )
    return _serialize_rows(rows)


# --- Health ----------------------------------------------------------------


@router.get("/health")
async def health():
    try:
        p = await db.pool()
        async with p.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)}
    return {"status": "ok"}


# --- Helpers ---------------------------------------------------------------


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
