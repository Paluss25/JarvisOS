"""Tests for EIA digest writer helpers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.email_intelligence_agent.tools import _compute_action_hint, _write_to_digest


def test_hint_blocked_forwards_to_cos():
    assert _compute_action_hint({"blocked": True}) == "forward_to_cos"


def test_hint_high_risk_forwards_to_cos():
    payload = {
        "blocked": False,
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "personal",
            "risk_level": "high",
            "sensitivity": "private",
            "priority": "normal",
        },
        "subject": "hello",
    }
    assert _compute_action_hint(payload) == "forward_to_cos"


def test_hint_newsletter_archives():
    payload = {
        "blocked": False,
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "newsletter",
            "risk_level": "low",
            "sensitivity": "public",
            "priority": "low",
        },
        "subject": "weekly digest",
    }
    assert _compute_action_hint(payload) == "archive"


def test_hint_invoice_subject_creates_task():
    payload = {
        "blocked": False,
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "finance",
            "risk_level": "low",
            "sensitivity": "private",
            "priority": "normal",
        },
        "subject": "Fattura n.2026-001",
    }
    assert _compute_action_hint(payload) == "create_task"


def test_hint_personal_allowed_drafts_reply():
    payload = {
        "blocked": False,
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "personal",
            "risk_level": "low",
            "sensitivity": "private",
            "priority": "normal",
        },
        "subject": "Ciao come stai?",
    }
    assert _compute_action_hint(payload) == "draft_reply"


def test_hint_unknown_domain_forwards_to_cos():
    payload = {
        "blocked": False,
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "other",
            "risk_level": "low",
            "sensitivity": "private",
            "priority": "normal",
        },
        "subject": "random email",
    }
    assert _compute_action_hint(payload) == "forward_to_cos"


def test_write_to_digest_creates_file(tmp_path):
    digest = tmp_path / "mt_digest.json"
    _write_to_digest({"email_id": "abc", "mt_action_hint": "archive"}, digest)
    assert digest.exists()
    lines = digest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["email_id"] == "abc"


def test_write_to_digest_appends(tmp_path):
    digest = tmp_path / "mt_digest.json"
    _write_to_digest({"email_id": "1", "mt_action_hint": "archive"}, digest)
    _write_to_digest({"email_id": "2", "mt_action_hint": "draft_reply"}, digest)
    lines = digest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["email_id"] == "2"
