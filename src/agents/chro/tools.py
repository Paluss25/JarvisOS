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
    (re.compile(
        r'\b(Via|Viale|Corso|C\.so|Piazza|P\.zza|Largo|Vicolo|Via\s+S\.|c/o)\s+[A-Za-zÀ-ÿ\s.]+,?\s*\d+\b',
        re.IGNORECASE,
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

    all_tools = [daily_log, memory_search, memory_get, query_db, receive_document, extract_text, sanitize_pii_tool]
    if send_message is not None:
        all_tools.append(send_message)

    try:
        server = create_sdk_mcp_server(name="chro-tools", tools=all_tools)
        logger.info("mcp_server: CHRO tools registered (%d tools)", len(all_tools))
        return server
    except Exception as exc:
        logger.warning("mcp_server: failed to create server — %s", exc)
        return None
