"""Unit tests for agents.chro.extractor.

Tests use a mocked async llm_call — no real LLM is invoked.
The CHRO_SCHEMA_DIR is pointed at the in-repo memory/schemas directory so
schema validation runs against the production JSON schemas.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# Point the extractor at the in-repo schema directory before import.
_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "memory" / "schemas"
os.environ.setdefault("CHRO_SCHEMA_DIR", str(_SCHEMA_DIR))

from agents.chro import extractor  # noqa: E402


@pytest.mark.asyncio
async def test_extract_payslip_strips_code_fences():
    async def fake_llm(prompt: str) -> str:
        return (
            '```json\n'
            '{"month":3,"year":2026,"net_amount":2100,"gross_amount":3000}\n'
            '```'
        )
    out = await extractor.extract_fields("dummy", "payslip", fake_llm)
    assert out["month"] == 3
    assert out["year"] == 2026
    assert out["net_amount"] == 2100


@pytest.mark.asyncio
async def test_extract_expense():
    async def fake_llm(prompt: str) -> str:
        return (
            '{"expense_date":"2026-04-15","category":"trasferta",'
            '"amount_eur":150,"reimbursement_status":"pending"}'
        )
    out = await extractor.extract_fields("dummy", "expense_report", fake_llm)
    assert out["category"] == "trasferta"


@pytest.mark.asyncio
async def test_extract_unknown_doc_type_raises():
    async def fake_llm(prompt: str) -> str:
        return "{}"

    with pytest.raises(ValueError):
        await extractor.extract_fields("x", "not_a_doc_type", fake_llm)
