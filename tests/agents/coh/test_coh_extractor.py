"""Unit tests for agents.coh.extractor.

Tests use a mocked async llm_call — no real LLM is invoked.
The COH_SCHEMA_DIR is pointed at the in-repo memory/schemas directory so
schema validation runs against the production JSON schemas.

Note: no __init__.py in this directory — pytest collects tests via
rootdir / pythonpath = src (see pytest.ini). Adding __init__.py here
collides with the chro test package and breaks collection.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# Point the extractor at the in-repo schema directory before import.
_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "memory" / "schemas"
os.environ.setdefault("COH_SCHEMA_DIR", str(_SCHEMA_DIR))

from agents.coh import extractor  # noqa: E402


@pytest.mark.asyncio
async def test_extract_lab_panel_strips_code_fences():
    """The extractor must tolerate ```json fenced LLM output and validate
    against the lab_panel schema."""
    sample = (
        "```json\n"
        "{\n"
        '  "panel_name": "Emocromo completo",\n'
        '  "lab_name": "Synlab",\n'
        '  "physician": "Dr. Mario Bianchi",\n'
        '  "collection_date": "2026-04-15",\n'
        '  "report_date": "2026-04-17",\n'
        '  "values": [\n'
        '    {"parameter_name": "Glicemia", "value": 95, "unit": "mg/dL",'
        ' "ref_range_low": 70, "ref_range_high": 100},\n'
        '    {"parameter_name": "HDL", "value": 55, "unit": "mg/dL",'
        ' "ref_range_low": 40, "ref_range_high": null}\n'
        "  ]\n"
        "}\n"
        "```"
    )

    async def fake_llm(prompt: str) -> str:
        return sample

    out = await extractor.extract_lab_panel("dummy", fake_llm)
    assert out["panel_name"] == "Emocromo completo"
    assert out["lab_name"] == "Synlab"
    assert out["collection_date"] == "2026-04-15"
    assert len(out["values"]) == 2
    assert out["values"][0]["parameter_name"] == "Glicemia"
    assert out["values"][0]["value"] == 95
    assert out["values"][1]["ref_range_high"] is None


@pytest.mark.asyncio
async def test_extract_medical_report():
    """Plain JSON output must validate against the medical_report schema."""
    sample = (
        '{"report_type": "cardiologia",'
        ' "specialist": "Dr. Rossi",'
        ' "facility": "Ospedale X",'
        ' "report_date": "2026-04-20",'
        ' "summary": "Visita di controllo, nessuna alterazione."}'
    )

    async def fake_llm(prompt: str) -> str:
        return sample

    out = await extractor.extract_medical_report("dummy", fake_llm)
    assert out["report_type"] == "cardiologia"
    assert out["specialist"] == "Dr. Rossi"
    assert out["facility"] == "Ospedale X"
    assert out["report_date"] == "2026-04-20"
