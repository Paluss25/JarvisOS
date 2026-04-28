"""CHRO (Chief People Officer) MCP server — custom tools.

Tools (P1 skeleton):
  daily_log      — append entry to today's memory log
  memory_search  — text search across MEMORY.md + memory/*.md
  query_db       — SELECT on chro.* tables

Tools (added in P2):
  receive_document  — save uploaded file to NAS /hr-docs/inbox/
  extract_text      — pdfplumber or pytesseract text extraction
  sanitize_pii      — regex PII redaction (no LLM)
  classify_document — LLM (Haiku) document type classification
  extract_fields    — LLM (Haiku) structured field extraction with it-IT glossary
  validate_schema   — chro_cpo schema validation
  save_to_db        — INSERT into chro.* tables
  archive_doc       — move from inbox/ to archive/YYYY/tipo/
"""

import json
import logging
import os
import re
import shutil
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_args(args) -> dict:
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return args if isinstance(args, dict) else {}


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": str(s)}]}


try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def _coerce_params(params: list | None) -> list | None:
    if not params:
        return params
    out = []
    for p in params:
        if isinstance(p, str):
            if _DATETIME_RE.match(p):
                try:
                    out.append(datetime.fromisoformat(p))
                    continue
                except ValueError:
                    pass
            if _DATE_RE.match(p):
                try:
                    out.append(date.fromisoformat(p))
                    continue
                except ValueError:
                    pass
        out.append(p)
    return out


async def _pg_query(sql: str, params: list | None = None) -> list[dict]:
    import asyncpg
    url = os.environ.get("CHRO_POSTGRES_URL", "") or os.environ.get("JARVIOS_POSTGRES_URL", "")
    if not url:
        raise RuntimeError("CHRO_POSTGRES_URL (or JARVIOS_POSTGRES_URL) not configured")
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(sql, *(_coerce_params(params) or []))
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# PII redaction patterns — ordered most-specific first
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Italian codice fiscale: 16 alphanumeric chars (both upper and lower case)
    (re.compile(r'\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b', re.IGNORECASE), '[CF_REDACTED]'),
    # IBAN with optional spaces (IT format and generic European)
    (re.compile(r'\b[A-Z]{2}\d{2}[\s]?[A-Z0-9]{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?[A-Z0-9]{0,3}\b'), '[IBAN_REDACTED]'),
    # IBAN compact (no spaces) — covers long IBANs up to 34 chars
    (re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}[A-Z0-9]{0,16}\b'), '[IBAN_REDACTED]'),
    # Italian VAT / P.IVA (with or without "IT" prefix, with or without spaces/dots)
    (re.compile(r'\b(IT)?\s?P\.?\s?IVA\s*:?\s*\d{11}\b', re.IGNORECASE), '[PIVA_REDACTED]'),
    # P.IVA bare number (11 digits following typical IT VAT context)
    (re.compile(r'\bIT\s?\d{11}\b'), '[PIVA_REDACTED]'),
    # Street address patterns — including abbreviated forms (P.zza, C.so, Via S., c/o)
    # Corso/Largo require an uppercase first letter after the keyword to avoid false positives
    # on common Italian HR phrases like "Corso di formazione..." or "Largo accordo..."
    (re.compile(
        r'\b(Via|Viale|C\.so|Piazza|P\.zza|Vicolo|Via\s+S\.|c/o)\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s.]*,?\s*\d+\b'
        r'|'
        r'\b(Corso|Largo)\s+[A-Z][A-Za-zÀ-ÿ\s.]*,?\s*\d+\b',
        re.UNICODE,
    ), '[ADDR_REDACTED]'),
]


def sanitize_pii(text: str, extra_names: list[str] | None = None) -> str:
    """Redact PII from document text before any LLM call. Purely local — no network."""
    result = text
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)
    if extra_names:
        for name in extra_names:
            if len(name) >= 3:
                result = re.sub(re.escape(name), '[NAME_REDACTED]', result, flags=re.IGNORECASE)
    return result


_CLASSIFY_KEYWORDS = {
    "payslip": ["retribuzione", "cedolino", "busta paga", "netto", "lordo", "irpef", "inps a carico dipendente", "tfr competenza"],
    "leave_statement": ["ferie residue", "prospetto ferie", "rol residuo", "permessi residui"],
    "inps_extract": ["estratto conto inps", "anzianità contributiva", "contributi versati", "gestione separata"],
    "expense_report": ["nota spese", "rimborso spese", "trasferta", "km percorsi"],
}


class ValidationError(ValueError):
    pass


_SCHEMA_PATHS = {
    "payslip": "/app/memory/schemas/payslip.json",
    "leave_statement": "/app/memory/schemas/leave_statement.json",
    "inps_extract": "/app/memory/schemas/inps_extract.json",
    "expense_report": "/app/memory/schemas/expense_report.json",
}


def validate_extracted_fields(doc_type: str, fields: dict) -> None:
    """Validate extracted fields against the JSON schema. Raises ValidationError on failure."""
    schema_path = _SCHEMA_PATHS.get(doc_type)
    if not schema_path:
        raise ValidationError(f"No schema registered for doc_type: {doc_type}")
    # Fall back to local dev path when running outside container
    if not Path(schema_path).exists():
        local_path = Path(__file__).parent.parent.parent.parent / "memory" / "schemas" / f"{doc_type}.json"
        if local_path.exists():
            schema_path = str(local_path)
    try:
        from chro_cpo.schemas.validators import validate_payload
        validate_payload(schema_path, fields)
    except Exception as exc:
        raise ValidationError(str(exc)) from exc


def classify_document_from_text(text: str) -> str:
    """Fast keyword-based document classification. Used as pre-LLM check."""
    lower = text.lower()
    scores = {dtype: sum(1 for kw in kws if kw in lower) for dtype, kws in _CLASSIFY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def extract_text_from_bytes(content: bytes, filename: str) -> str:
    """Extract text from PDF bytes using pdfplumber, fallback to pytesseract for scanned PDFs."""
    import pdfplumber
    import io

    ext = Path(filename).suffix.lower()

    if ext in (".jpg", ".jpeg", ".png"):
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        return pytesseract.image_to_string(img, lang="ita") or ""

    # PDF path
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            ).strip()
        if len(text) > 5:
            return text
    except Exception:
        pass

    # Fallback: OCR the PDF pages as images
    try:
        import pytesseract
        from PIL import Image
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            lines = []
            for page in pdf.pages:
                img = page.to_image(resolution=200).original
                lines.append(pytesseract.image_to_string(img, lang="ita") or "")
        return "\n".join(lines).strip()
    except Exception as exc:
        logger.warning("extract_text_from_bytes: OCR fallback failed — %s", exc)
        return ""


def archive_document(
    src_path: str,
    doc_type: str,
    archive_root: Path | None = None,
    period_year: int | None = None,
) -> str:
    """Move a file from inbox to archive/YYYY/doc_type/ and return the new path."""
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"Source not found: {src_path}")
    root = archive_root or Path("/app/hr-docs/archive")
    year = period_year if period_year else datetime.now().year
    dest_dir = root / str(year) / doc_type
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        stem, suffix = src.stem, src.suffix
        dest = dest_dir / f"{stem}_{int(datetime.now().timestamp())}{suffix}"
    shutil.move(str(src), str(dest))
    return str(dest)


async def _run_payroll_specialist(case) -> dict:
    """Payroll Intelligence Agent — queries payslips DB for the case."""
    rows = await _pg_query(
        "SELECT id, period_from, period_to, employer, gross_pay, net_pay, irpef_withheld, "
        "inps_employee, tfr_accrued, leave_residual_days, rol_residual_hours "
        "FROM chro.payslips ORDER BY period_to DESC LIMIT 6"
    )
    if not rows:
        return {"agent_id": "payroll_intelligence", "confidence": 0.5,
                "payload": {"note": "No payslips in DB yet."}, "escalations": []}
    latest = rows[0]
    anomalies = []
    escalations = []
    if len(rows) >= 2:
        prev = rows[1]
        if prev["net_pay"] and latest["net_pay"]:
            delta_pct = abs((latest["net_pay"] - prev["net_pay"]) / prev["net_pay"])
            if delta_pct > 0.05:
                anomalies.append(
                    f"Net pay changed {delta_pct:.1%} vs previous month "
                    f"({prev['net_pay']:.2f} → {latest['net_pay']:.2f} EUR)"
                )
        if prev["inps_employee"] and latest["inps_employee"]:
            inps_delta = abs((latest["inps_employee"] - prev["inps_employee"]) / prev["inps_employee"])
            if inps_delta > 0.10:
                anomalies.append(
                    f"INPS contribution changed {inps_delta:.1%} — possible rate change or base change"
                )
                escalations.append("inps_anomaly_escalate_to_ceo")
    return {
        "agent_id": "payroll_intelligence",
        "confidence": 0.90,
        "payload": {
            "latest_payslip": dict(latest),
            "payslip_history": rows,
            "anomalies": anomalies,
        },
        "escalations": escalations,
    }


async def _run_leave_specialist(case) -> dict:
    """Leave, Time & Travel Agent — queries leave_snapshots DB."""
    rows = await _pg_query(
        "SELECT snapshot_date, ferie_accrued, ferie_used, ferie_remaining, "
        "rol_accrued, rol_used, rol_remaining "
        "FROM chro.leave_snapshots ORDER BY snapshot_date DESC LIMIT 3"
    )
    if not rows:
        return {"agent_id": "leave_time_travel", "confidence": 0.5,
                "payload": {"note": "No leave snapshots in DB yet."}}
    latest = rows[0]
    flags = []
    if latest.get("ferie_remaining") is not None and latest["ferie_remaining"] < 5:
        flags.append(f"Ferie residue criticamente basse: {latest['ferie_remaining']} giorni")
    return {
        "agent_id": "leave_time_travel",
        "confidence": 0.90,
        "payload": {"latest_snapshot": dict(latest), "flags": flags},
    }


async def _run_pension_specialist(case) -> dict:
    """Pension & Benefits Agent — queries pension_extracts DB."""
    rows = await _pg_query(
        "SELECT document_date, contribution_period, total_contributions, "
        "projected_pension_age, projected_monthly_pension "
        "FROM chro.pension_extracts ORDER BY document_date DESC LIMIT 2"
    )
    if not rows:
        return {"agent_id": "pension_benefits", "confidence": 0.5,
                "payload": {"note": "No pension extracts in DB yet."}}
    return {
        "agent_id": "pension_benefits",
        "confidence": 0.85,
        "payload": {"latest_extract": dict(rows[0])},
    }


async def _run_director(case) -> dict:
    """Director of Workforce Administration — parallel multi-domain dispatch."""
    import asyncio
    payroll_task = asyncio.create_task(_run_payroll_specialist(case))
    leave_task = asyncio.create_task(_run_leave_specialist(case))
    pension_task = asyncio.create_task(_run_pension_specialist(case))
    payroll, leave, pension = await asyncio.gather(payroll_task, leave_task, pension_task)
    return {
        "agent_id": "director_workforce_admin",
        "confidence": min(payroll["confidence"], leave["confidence"], pension["confidence"]),
        "payload": {
            "payroll": payroll["payload"],
            "leave": leave["payload"],
            "pension": pension["payload"],
        },
    }


def create_chro_mcp_server(workspace_path: Path, redis_a2a=None):
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk not available — CHRO tools disabled")
        return None

    # ---- Memory tools -------------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's CHRO memory log. Use this to record significant HR events, "
        "decisions, or flags worth remembering (e.g. anomaly detected, document processed, action taken).",
        {"message": str},
    )
    async def daily_log(args: dict) -> dict:
        args = _parse_args(args)
        message = args.get("message", "")
        if not message:
            return _text("No message provided.")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(message)
            return _text(f"Logged: {message[:80]}")
        except Exception as exc:
            logger.error("daily_log: failed — %s", exc)
            return _text(f"Failed to log: {exc}")

    @sdk_tool(
        "memory_search",
        "Search across CHRO long-term memory (MEMORY.md) and daily logs (memory/*.md) using text matching. "
        "Use this to recall past payslip anomalies, HR flags, or decisions.",
        {"query": str, "top_k": int},
    )
    async def memory_search(args: dict) -> dict:
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return _text("No query provided.")
        top_k = int(args.get("top_k") or 5)
        query_lower = query.lower()
        memory_dir = workspace_path / "memory"
        dated_files = sorted(memory_dir.glob("*.md"), reverse=True) if memory_dir.exists() else []
        files_to_search = list(dated_files) + [workspace_path / "MEMORY.md"]
        results = []
        for f in files_to_search:
            if not f.exists():
                continue
            try:
                lines = f.read_text(encoding="utf-8").split("\n")
            except OSError:
                continue
            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = "\n".join(lines[start:end])
                    results.append(f"**{f.name}** (line {i + 1}):\n```\n{snippet}\n```")
                    if len(results) >= top_k:
                        break
            if len(results) >= top_k:
                break
        if not results:
            return _text(f"No results found for '{query}'.")
        return _text("\n\n---\n\n".join(results))

    # ---- Database query tool ------------------------------------------------

    @sdk_tool(
        "query_db",
        "Execute a read-only SELECT query against the chro PostgreSQL schema. "
        "Tables: chro.payslips, chro.leave_snapshots, chro.pension_extracts, chro.expense_items, chro.hr_audit_log. "
        "Only SELECT statements are allowed.",
        {
            "query": str,
            "params": {"type": "array", "items": {}, "default": []},
        },
    )
    async def query_db(args: dict) -> dict:
        args = _parse_args(args)
        sql = (args.get("query") or "").strip()
        raw_params = args.get("params") or []
        if isinstance(raw_params, str):
            try:
                raw_params = json.loads(raw_params)
            except Exception:
                raw_params = []
        params = raw_params if isinstance(raw_params, list) else []
        if not sql:
            return _text("No query provided.")
        if not re.match(r'\s*SELECT\b', sql, re.IGNORECASE):
            return _text("query_db only accepts SELECT statements.")
        if not re.search(r'\bchro\.', sql, re.IGNORECASE):
            return _text("query_db only allows queries against the chro schema.")
        try:
            rows = await _pg_query(sql, params or None)
            return {"content": [{"type": "text", "text": json.dumps(rows, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("query_db: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Query error: {exc}"}], "is_error": True}

    # ---- Memory read tool ---------------------------------------------------

    @sdk_tool(
        "memory_get",
        "Read a specific memory file from the workspace. "
        "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
        "Optionally specify start_line and num_lines to read a slice.",
        {"path": str, "start_line": {"type": "integer", "default": 1}, "num_lines": {"type": "integer", "default": 50}},
    )
    async def memory_get(args: dict) -> dict:
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return _text("No path provided.")
        target = (workspace_path / rel_path).resolve()
        try:
            target.relative_to(workspace_path.resolve())
        except ValueError:
            return _text("Access denied: path is outside the workspace directory.")
        if not target.exists():
            return _text(f"File not found: {rel_path}")
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _text(f"Error reading {rel_path}: {exc}")
        start_line = args.get("start_line")
        num_lines = args.get("num_lines")
        if start_line is not None or num_lines is not None:
            lines = content.split("\n")
            s = int(start_line or 1) - 1
            n = int(num_lines) if num_lines is not None else len(lines)
            content = "\n".join(lines[s: s + n])
        return _text(content)

    # ---- Document pipeline tools --------------------------------------------

    @sdk_tool(
        "receive_document",
        "Save an uploaded HR document (PDF, JPG, PNG) to the NAS inbox. "
        "Pass the raw file bytes as a base64-encoded string or a file path already on disk. "
        "Returns the saved path on the NAS.",
        {"filename": str, "content_b64": str},
    )
    async def receive_document(args: dict) -> dict:
        args = _parse_args(args)
        filename = (args.get("filename") or "").strip()
        content_b64 = (args.get("content_b64") or "").strip()
        if not filename or not content_b64:
            return _text("filename and content_b64 are required.")
        import base64
        try:
            content = base64.b64decode(content_b64)
        except Exception as exc:
            return _text(f"Invalid base64 content: {exc}")
        inbox = Path("/app/hr-docs/inbox")
        inbox.mkdir(parents=True, exist_ok=True)
        dest = inbox / Path(filename).name  # basename only — prevents path traversal
        dest.write_bytes(content)
        return _text(f"Saved to {dest}")

    @sdk_tool(
        "extract_text",
        "Extract text from a document file on the NAS. "
        "Pass the full path (e.g. /app/hr-docs/inbox/cedolino-2026-03.pdf). "
        "Returns the extracted text. For scanned PDFs, OCR is used automatically.",
        {"path": str},
    )
    async def extract_text(args: dict) -> dict:
        args = _parse_args(args)
        path_str = (args.get("path") or "").strip()
        if not path_str:
            return _text("path is required.")
        p = Path(path_str)
        if not p.exists():
            return _text(f"File not found: {path_str}")
        content = p.read_bytes()
        text = extract_text_from_bytes(content, p.name)
        if not text:
            return _text("Could not extract text — document may be empty or unsupported format.")
        return _text(sanitize_pii(text))

    @sdk_tool(
        "classify_document",
        "Classify a sanitized document text into one of: payslip, leave_statement, inps_extract, expense_report, unknown. "
        "Uses keyword matching first; falls back to LLM (Haiku) when ambiguous. "
        "text MUST already be PII-sanitized before calling this tool.",
        {"text": str},
    )
    async def classify_document(args: dict) -> dict:
        args = _parse_args(args)
        text = (args.get("text") or "").strip()
        if not text:
            return _text("No text provided.")
        text = sanitize_pii(text)  # enforce PII sanitization before any LLM call

        doc_type = classify_document_from_text(text)
        if doc_type != "unknown":
            return _text(doc_type)

        # Slow path: LLM classification (Haiku)
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            model = os.environ.get("CLAUDE_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
            response = client.messages.create(
                model=model,
                max_tokens=50,
                messages=[{
                    "role": "user",
                    "content": (
                        "Classify this Italian HR document into exactly one category. "
                        "Reply with only one word from: payslip, leave_statement, inps_extract, expense_report, unknown.\n\n"
                        f"DOCUMENT (first 1500 chars):\n{text[:1500]}"
                    ),
                }],
            )
            result = response.content[0].text.strip().lower()
            valid = {"payslip", "leave_statement", "inps_extract", "expense_report", "unknown"}
            return _text(result if result in valid else "unknown")
        except Exception as exc:
            logger.error("classify_document LLM fallback failed: %s", exc)
            return _text("unknown")

    @sdk_tool(
        "extract_fields",
        "Extract structured fields from a sanitized HR document text using LLM + Italian locale vocabulary. "
        "doc_type must be one of: payslip, leave_statement, inps_extract, expense_report. "
        "text MUST already be PII-sanitized. Returns a JSON object with extracted fields.",
        {"text": str, "doc_type": str},
    )
    async def extract_fields(args: dict) -> dict:
        args = _parse_args(args)
        text = (args.get("text") or "").strip()
        doc_type = (args.get("doc_type") or "").strip()
        if not text or not doc_type:
            return _text("text and doc_type are required.")
        text = sanitize_pii(text)  # enforce PII sanitization before any LLM call

        locale_path = workspace_path / "knowledge" / "it-IT-locale.json"
        locale = {}
        if locale_path.exists():
            try:
                locale = json.loads(locale_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        payroll_vocab = json.dumps(locale.get("payroll_fields", {}), ensure_ascii=False)
        law_ref = json.dumps(locale.get("law_reference", {}), ensure_ascii=False)

        schema_hints = {
            "payslip": "period_from (YYYY-MM-DD), period_to (YYYY-MM-DD), employer (string), gross_pay (number EUR), net_pay (number EUR), inps_employee (number EUR), irpef_withheld (number EUR), tfr_accrued (number EUR), leave_residual_days (number), rol_residual_hours (number)",
            "leave_statement": "snapshot_date (YYYY-MM-DD), ferie_accrued (number days), ferie_used (number days), ferie_remaining (number days), rol_accrued (number hours), rol_used (number hours), rol_remaining (number hours)",
            "inps_extract": "document_date (YYYY-MM-DD), contribution_period (string e.g. '2010-01 / 2026-03'), total_contributions (number EUR), projected_pension_age (integer), projected_monthly_pension (number EUR)",
            "expense_report": "expense_date (YYYY-MM-DD), category (string), amount_eur (number), reimbursed (boolean), employer_reference (string)",
        }.get(doc_type, "")

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            model = os.environ.get("CLAUDE_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
            prompt = (
                f"Extract structured fields from this Italian HR document (type: {doc_type}).\n\n"
                f"Italian field vocabulary mapping:\n{payroll_vocab}\n\n"
                f"Italian labor law reference:\n{law_ref}\n\n"
                f"Required output fields:\n{schema_hints}\n\n"
                "Return a JSON object only — no explanation, no markdown. "
                "Use null for missing fields. All monetary values as plain numbers (EUR).\n\n"
                f"DOCUMENT (PII already redacted):\n{text[:3000]}"
            )
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            extracted = json.loads(raw)
            return {"content": [{"type": "text", "text": json.dumps(extracted, ensure_ascii=False)}]}
        except json.JSONDecodeError as exc:
            return _text(f"LLM returned non-JSON response: {exc}")
        except Exception as exc:
            logger.error("extract_fields failed: %s", exc)
            return {"content": [{"type": "text", "text": f"Extraction error: {exc}"}], "is_error": True}

    @sdk_tool(
        "sanitize_pii",
        "Redact PII from document text before passing to any LLM. "
        "Replaces: codice fiscale → [CF_REDACTED], IBAN → [IBAN_REDACTED], "
        "street addresses → [ADDR_REDACTED], P.IVA → [PIVA_REDACTED]. "
        "Pass extra_names as a list of name strings to also redact (e.g. ['Mario Rossi']).",
        {"text": str, "extra_names": {"type": "array", "items": {"type": "string"}, "default": []}},
    )
    async def sanitize_pii_tool(args: dict) -> dict:
        args = _parse_args(args)
        text = args.get("text", "")
        extra_names = args.get("extra_names") or []
        if not text:
            return _text("No text provided.")
        redacted = sanitize_pii(text, extra_names=extra_names or None)
        return _text(redacted)

    @sdk_tool(
        "validate_schema",
        "Validate extracted fields against the expected schema for the document type. "
        "doc_type: payslip | leave_statement | inps_extract | expense_report. "
        "fields: the JSON object returned by extract_fields. "
        "Returns 'valid' or raises a validation error message.",
        {"doc_type": str, "fields": {"type": "object"}},
    )
    async def validate_schema(args: dict) -> dict:
        args = _parse_args(args)
        doc_type = (args.get("doc_type") or "").strip()
        fields = args.get("fields") or {}
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except Exception:
                return _text("fields must be a JSON object.")
        if not doc_type:
            return _text("doc_type is required.")
        try:
            validate_extracted_fields(doc_type, fields)
            return _text("valid")
        except ValidationError as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "is_error": True}

    @sdk_tool(
        "save_to_db",
        "INSERT validated extracted fields into the appropriate chro.* table. "
        "doc_type: payslip | leave_statement | inps_extract | expense_report. "
        "fields: the validated JSON object. case_id: UUID string for audit log grouping. "
        "source_file: the NAS path of the original document.",
        {"doc_type": str, "fields": {"type": "object"}, "case_id": str, "source_file": str},
    )
    async def save_to_db(args: dict) -> dict:
        args = _parse_args(args)
        doc_type = (args.get("doc_type") or "").strip()
        fields = args.get("fields") or {}
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except Exception:
                return _text("fields must be a JSON object.")
        case_id = (args.get("case_id") or "").strip()
        source_file = (args.get("source_file") or "").strip()

        import asyncpg
        import datetime as _dt
        import uuid as _uuid

        def _to_date(val):
            if val is None:
                return None
            if isinstance(val, _dt.date):
                return val
            return _dt.date.fromisoformat(str(val))

        def _to_uuid(val):
            if val is None:
                return None
            if isinstance(val, _uuid.UUID):
                return val
            return _uuid.UUID(str(val))

        url = os.environ.get("CHRO_POSTGRES_URL", "") or os.environ.get("JARVIOS_POSTGRES_URL", "")
        if not url:
            return _text("CHRO_POSTGRES_URL not configured.")

        try:
            conn = await asyncpg.connect(url)
            try:
                async with conn.transaction():
                    if doc_type == "payslip":
                        row = await conn.fetchrow(
                            """INSERT INTO chro.payslips
                               (period_from, period_to, employer, gross_pay, net_pay,
                                inps_employee, irpef_withheld, tfr_accrued,
                                leave_residual_days, rol_residual_hours, raw_json, source_file)
                               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                               RETURNING id""",
                            _to_date(fields.get("period_from")), _to_date(fields.get("period_to")),
                            fields.get("employer"), fields.get("gross_pay"), fields.get("net_pay"),
                            fields.get("inps_employee"), fields.get("irpef_withheld"),
                            fields.get("tfr_accrued"), fields.get("leave_residual_days"),
                            fields.get("rol_residual_hours"),
                            json.dumps(fields), source_file,
                        )
                        record_id = str(row["id"])

                    elif doc_type == "leave_statement":
                        row = await conn.fetchrow(
                            """INSERT INTO chro.leave_snapshots
                               (snapshot_date, ferie_accrued, ferie_used, ferie_remaining,
                                rol_accrued, rol_used, rol_remaining)
                               VALUES ($1,$2,$3,$4,$5,$6,$7)
                               RETURNING id""",
                            _to_date(fields.get("snapshot_date")),
                            fields.get("ferie_accrued"), fields.get("ferie_used"), fields.get("ferie_remaining"),
                            fields.get("rol_accrued"), fields.get("rol_used"), fields.get("rol_remaining"),
                        )
                        record_id = str(row["id"])

                    elif doc_type == "inps_extract":
                        row = await conn.fetchrow(
                            """INSERT INTO chro.pension_extracts
                               (document_date, contribution_period, total_contributions,
                                projected_pension_age, projected_monthly_pension, raw_json, source_file)
                               VALUES ($1,$2,$3,$4,$5,$6,$7)
                               RETURNING id""",
                            _to_date(fields.get("document_date")), fields.get("contribution_period"),
                            fields.get("total_contributions"), fields.get("projected_pension_age"),
                            fields.get("projected_monthly_pension"),
                            json.dumps(fields), source_file,
                        )
                        record_id = str(row["id"])

                    elif doc_type == "expense_report":
                        row = await conn.fetchrow(
                            """INSERT INTO chro.expense_items
                               (expense_date, category, amount_eur, reimbursed, employer_reference)
                               VALUES ($1,$2,$3,$4,$5)
                               RETURNING id""",
                            _to_date(fields.get("expense_date")), fields.get("category"),
                            fields.get("amount_eur"), bool(fields.get("reimbursed", False)),
                            fields.get("employer_reference"),
                        )
                        record_id = str(row["id"])

                    else:
                        return _text(f"Unknown doc_type: {doc_type}")

                    await conn.execute(
                        """INSERT INTO chro.hr_audit_log
                           (case_id, agent_id, action, output_schema_version, confidence)
                           VALUES ($1, $2, $3, $4, $5)""",
                        _to_uuid(case_id or record_id), "chro", f"save_to_db:{doc_type}", "1.0",
                        float(fields.get("confidence", 0.0)) if fields.get("confidence") else None,
                    )

                return _text(f"Saved {doc_type} record id={record_id}")
            finally:
                await conn.close()
        except Exception as exc:
            logger.error("save_to_db(%s): error — %s", doc_type, exc)
            return {"content": [{"type": "text", "text": f"DB error: {exc}"}], "is_error": True}

    @sdk_tool(
        "archive_doc",
        "Move a processed document from /app/hr-docs/inbox/ to /app/hr-docs/archive/YYYY/doc_type/. "
        "Call this AFTER save_to_db succeeds. "
        "src_path: full path of the file in inbox (e.g. /app/hr-docs/inbox/cedolino-2026-03.pdf). "
        "doc_type: payslip | leave_statement | inps_extract | expense_report. "
        "period_year: the year from the document's period_from or document_date field (e.g. 2026).",
        {"src_path": str, "doc_type": str, "period_year": int},
    )
    async def archive_doc(args: dict) -> dict:
        args = _parse_args(args)
        src_path = (args.get("src_path") or "").strip()
        doc_type = (args.get("doc_type") or "").strip()
        period_year = args.get("period_year") or None
        if not src_path or not doc_type:
            return _text("src_path and doc_type are required.")
        try:
            dest = archive_document(src_path, doc_type, period_year=period_year)
            return _text(f"Archived to {dest}")
        except FileNotFoundError as exc:
            return _text(str(exc))
        except Exception as exc:
            logger.error("archive_doc: error — %s", exc)
            return {"content": [{"type": "text", "text": f"Archive error: {exc}"}], "is_error": True}

    # ---- Specialist routing tool --------------------------------------------

    _local_send_fn = None
    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _local_send_fn = create_send_message_tool("chro", redis_a2a)

    @sdk_tool(
        "dispatch_to_specialist",
        "Dispatch an HR task to the appropriate headless specialist agent via the Director of Workforce Administration. "
        "The Director uses keyword-based routing to select: payroll_intelligence, leave_time_travel, or pension_benefits. "
        "Multi-domain queries are handled by the Director directly (parallel dispatch). "
        "text: the sanitized request text (PII already removed). "
        "domain: optional hint ('payroll', 'leave', 'pension', 'multi'). "
        "Returns a specialist result dict.",
        {"text": str, "domain": str},
    )
    async def dispatch_to_specialist(args: dict) -> dict:
        args = _parse_args(args)
        text = (args.get("text") or "").strip()
        domain = (args.get("domain") or "").strip()
        if not text:
            return _text("text is required.")

        from chro_cpo.core.types import CaseEnvelope
        from chro_cpo.core.routing import Router
        import uuid

        case = CaseEnvelope(
            case_id=str(uuid.uuid4()),
            domain=domain or "hr",
            intent="analyze",
            risk="low",
            data_sensitivity="high",
            jurisdiction="IT",
            actionability="immediate",
            input_text=text,
        )

        route = Router().route(case)
        logger.info("dispatch_to_specialist: routing to %s", route)

        try:
            if route == "payroll_intelligence":
                result = await _run_payroll_specialist(case)
            elif route == "leave_time_travel":
                result = await _run_leave_specialist(case)
            elif route == "pension_benefits":
                result = await _run_pension_specialist(case)
            else:
                # director_workforce_admin: multi-domain parallel dispatch
                result = await _run_director(case)

            # Explicit INPS escalation — not left to agent reasoning
            if route in ("payroll_intelligence", "director_workforce_admin"):
                escalations = result.get("escalations", [])
                if "inps_anomaly_escalate_to_ceo" in escalations and _local_send_fn:
                    anomaly_text = ", ".join(
                        a for a in result.get("payload", {}).get("anomalies", [])
                        if "INPS" in a
                    )
                    try:
                        await _local_send_fn({
                            "to": "jarvis",
                            "message": (
                                f"INPS anomaly detected during payroll analysis: {anomaly_text}. "
                                "Please review and advise."
                            ),
                        })
                        logger.info("dispatch_to_specialist: INPS escalation sent to jarvis")
                    except Exception as exc:
                        logger.warning("dispatch_to_specialist: INPS escalation failed — %s", exc)

            return {"content": [{"type": "text", "text": json.dumps(result, default=str, indent=2)}]}
        except Exception as exc:
            logger.error("dispatch_to_specialist(%s): error — %s", route, exc)
            return {"content": [{"type": "text", "text": f"Specialist error: {exc}"}], "is_error": True}

    # ---- A2A send_message ---------------------------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("chro", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'ceo', 'cfo'). "
            "'message' is the natural language request.",
            {"to": str, "message": str},
        )
        async def send_message(args: dict) -> dict:
            args = _parse_args(args)
            return _text(await _send_message_fn(args))
    else:
        send_message = None

    all_tools = [
        daily_log, memory_search, memory_get, query_db,
        receive_document, extract_text,
        sanitize_pii_tool, classify_document, extract_fields,
        validate_schema, save_to_db, archive_doc,
        dispatch_to_specialist,
    ]
    if send_message is not None:
        all_tools.append(send_message)

    try:
        server = create_sdk_mcp_server(name="chro-tools", tools=all_tools)
        logger.info("mcp_server: CHRO tools registered (%d tools)", len(all_tools))
        return server
    except Exception as exc:
        logger.warning("mcp_server: failed to create server — %s", exc)
        return None
