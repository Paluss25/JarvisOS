"""LLM extraction for HR doc types.

Calls a caller-supplied async LLM and validates the parsed JSON against a
JSON schema located at /app/memory/schemas/<doc_type>.json (override via
CHRO_SCHEMA_DIR).

The LLM call is injected as a coroutine so this module stays independent
from any specific model wrapper. See `agents.chro.api._llm_call` for the
production binding.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# Schema directory inside the container.
SCHEMA_DIR = Path(os.environ.get("CHRO_SCHEMA_DIR", "/app/memory/schemas"))

# Map doc_type -> schema filename.
_SCHEMA_FILES = {
    "payslip": "payslip.json",
    "expense_report": "expense_report.json",
    "contract": "contract.json",
    "leonardo_doc": "leonardo_doc.json",
    "leave_statement": "leave_statement.json",
    "inps_extract": "inps_extract.json",
}

_PROMPT_TEMPLATES: dict[str, str] = {
    "payslip": (
        "You are extracting structured data from an Italian payslip (cedolino paga). "
        "PII (employee name, CF, IBAN, address) is already redacted as [*_REDACTED]. "
        "Return JSON with these fields: month (integer 1-12), year (integer), "
        "employer (string), employee_name (string or '[NAME_REDACTED]'), "
        "employee_code (string or null), "
        "gross_amount (number, retribuzione lorda), net_amount (number, netto in busta), "
        "tax_amount (number, IRPEF), contribution_amount (number, INPS dipendente), "
        "extraction_confidence (number 0..1), notes (string or null), "
        "items (array of {{item_type, item_category, description, amount, quantity, rate, metadata}}). "
        "Do NOT invent values. Use null when a field is not present.\n\n"
        "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
    ),
    "expense_report": (
        "Extract structured data from this Italian expense report (nota spese). "
        "Return JSON: expense_date (YYYY-MM-DD), category, amount_eur (number), "
        "reimbursement_status (pending|submitted|reimbursed|rejected), employer_ref, notes.\n\n"
        "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
    ),
    "contract": (
        "Extract structured data from this Italian employment contract. "
        "Return JSON: contract_type (indeterminato|determinato|freelance|other), "
        "employer, role, start_date (YYYY-MM-DD), end_date (YYYY-MM-DD or null), "
        "gross_yearly (number).\n\n"
        "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
    ),
    "leonardo_doc": (
        "Extract metadata from this Leonardo work document. "
        "Return JSON: title, doc_date (YYYY-MM-DD or null), tags (array of strings).\n\n"
        "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
    ),
    "leave_statement": (
        "Extract leave/permits balance: leave_residual_days (number), rol_residual_hours (number), "
        "leave_used_ytd_days (number), snapshot_date (YYYY-MM-DD).\n\n"
        "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
    ),
    "inps_extract": (
        "Extract INPS contribution statement: contribution_period_from, contribution_period_to "
        "(YYYY-MM-DD), total_contributions_eur, expected_pension_age (integer), "
        "projected_monthly_eur, extract_date (YYYY-MM-DD).\n\n"
        "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
    ),
}


LlmCallable = Callable[[str], Awaitable[str]]


def load_schema(doc_type: str) -> dict[str, Any]:
    fname = _SCHEMA_FILES.get(doc_type)
    if not fname:
        raise ValueError(f"No schema registered for doc_type: {doc_type}")
    return json.loads((SCHEMA_DIR / fname).read_text(encoding="utf-8"))


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        # ```json\n...\n``` or ```\n...\n```
        body = raw[3:]
        if body.startswith("json"):
            body = body[4:]
        body = body.lstrip("\n")
        if body.endswith("```"):
            body = body[:-3]
        raw = body.strip()
    return raw


async def extract_fields(
    redacted_text: str,
    doc_type: str,
    llm_call: LlmCallable,
) -> dict[str, Any]:
    """Run LLM extraction on the redacted text, validate against schema, return dict.

    `llm_call(prompt)` must be a coroutine that returns the model's text reply.
    Raises ValueError when doc_type is unknown; bubbles json.JSONDecodeError on
    bad LLM output; bubbles jsonschema.ValidationError on schema failures.
    """
    template = _PROMPT_TEMPLATES.get(doc_type)
    if not template:
        raise ValueError(f"No prompt template for doc_type: {doc_type}")

    prompt = template.format(text=redacted_text[:20000])  # cap context
    raw = await llm_call(prompt)
    raw = _strip_code_fences(raw)
    fields = json.loads(raw)

    # Schema validation if jsonschema available; warn-only on missing schema dir.
    try:
        import jsonschema  # type: ignore
    except ImportError:
        logger.warning("jsonschema not available, skipping validation")
        return fields

    try:
        schema = load_schema(doc_type)
    except FileNotFoundError:
        logger.warning(
            "schema file not found for doc_type=%s in %s; skipping validation",
            doc_type, SCHEMA_DIR,
        )
        return fields

    jsonschema.validate(fields, schema)
    return fields
