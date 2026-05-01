"""LLM extraction for medical doc types: lab_panel and medical_report.

Calls a caller-supplied async LLM and validates the parsed JSON against a
JSON schema located at /app/memory/schemas/<doc_type>.json (override via
COH_SCHEMA_DIR).

The LLM call is injected as a coroutine so this module stays independent
from any specific model wrapper. See `agents.coh.api._llm_call` for the
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
SCHEMA_DIR = Path(os.environ.get("COH_SCHEMA_DIR", "/app/memory/schemas"))


_PROMPT_LAB_PANEL = (
    "You are extracting structured lab panel data from an Italian referto di "
    "analisi cliniche. PII (patient name, CF) is already redacted as "
    "[*_REDACTED]. Doctor name, lab name, and clinical values are intact. "
    "Extract JSON with these fields: "
    "panel_name (string, e.g. 'Emocromo completo'), "
    "lab_name (string), physician (string|null), "
    "collection_date (YYYY-MM-DD, prelievo), "
    "report_date (YYYY-MM-DD, referto emesso), "
    "values: array of {{parameter_name, value (number or null), "
    "value_text (string for non-numeric like 'Negativo'), "
    "unit (string), ref_range_low (number|null), ref_range_high (number|null), "
    "notes (string|null)}}.\n\n"
    "Do NOT invent values. Use null when a field is not present.\n\n"
    "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
)


_PROMPT_MEDICAL_REPORT = (
    "Extract metadata from this Italian medical report (referto). "
    "Return JSON: report_type (one of: radiologia|cardiologia|"
    "visita_specialistica|dimissione|prescrizione|other), "
    "specialist (doctor name, NOT redacted), facility (struttura), "
    "report_date (YYYY-MM-DD), summary (1-2 sentences in Italian "
    "describing the key findings).\n\n"
    "DOCUMENT:\n{text}\n\nReturn ONLY the JSON object."
)


LlmCallable = Callable[[str], Awaitable[str]]


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _strip_code_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        body = raw[3:]
        if body.startswith("json"):
            body = body[4:]
        body = body.lstrip("\n")
        if body.endswith("```"):
            body = body[:-3]
        raw = body.strip()
    return raw


async def extract_lab_panel(
    redacted_text: str, llm_call: LlmCallable
) -> dict[str, Any]:
    """Extract a lab panel (panel header + array of values)."""
    prompt = _PROMPT_LAB_PANEL.format(text=redacted_text[:30000])
    raw = await llm_call(prompt)
    raw = _strip_code_fences(raw)
    fields = json.loads(raw)

    try:
        import jsonschema  # type: ignore
    except ImportError:
        logger.warning("jsonschema not available, skipping validation")
        return fields

    try:
        schema = load_schema("lab_panel")
    except FileNotFoundError:
        logger.warning(
            "schema file not found for lab_panel in %s; skipping validation",
            SCHEMA_DIR,
        )
        return fields

    jsonschema.validate(fields, schema)
    return fields


async def extract_medical_report(
    redacted_text: str, llm_call: LlmCallable
) -> dict[str, Any]:
    """Extract metadata from a medical report (referto)."""
    prompt = _PROMPT_MEDICAL_REPORT.format(text=redacted_text[:20000])
    raw = await llm_call(prompt)
    raw = _strip_code_fences(raw)
    fields = json.loads(raw)

    try:
        import jsonschema  # type: ignore
    except ImportError:
        logger.warning("jsonschema not available, skipping validation")
        return fields

    try:
        schema = load_schema("medical_report")
    except FileNotFoundError:
        logger.warning(
            "schema file not found for medical_report in %s; skipping validation",
            SCHEMA_DIR,
        )
        return fields

    jsonschema.validate(fields, schema)
    return fields
