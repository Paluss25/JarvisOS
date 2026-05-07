"""Regression tests for EIA -> MT email handoff hardening."""

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

class _RedisStub:
    def on_message(self, _callback):
        return None


def _tool(server, name):
    for entry in server._tools:
        if entry.name == name:
            return entry
    raise AssertionError(f"tool not registered: {name}")


def _setup_audit_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "var" / "audit").mkdir(parents=True)


def test_send_message_tools_register_dict_schema(monkeypatch):
    """send_message schema must be the SDK input_schema, not annotations."""
    from agents.cos.tools import create_chief_of_staff_mcp_server
    from agents.email_intelligence_agent.tools import create_email_intelligence_mcp_server
    from agents.mt.tools import create_mt_mcp_server

    fake_send_message = types.SimpleNamespace(create_send_message_tool=lambda *_args, **_kw: AsyncMock())
    monkeypatch.setitem(sys.modules, "agent_runner.tools.send_message", fake_send_message)

    servers = [
        create_mt_mcp_server(Path("/tmp/mt"), redis_a2a=_RedisStub()),
        create_email_intelligence_mcp_server(Path("/tmp/eia"), redis_a2a=_RedisStub()),
        create_chief_of_staff_mcp_server(Path("/tmp/cos"), redis_a2a=_RedisStub()),
    ]

    for server in servers:
        schema = _tool(server, "send_message").schema
        assert isinstance(schema, dict)
        assert {"to", "message", "wait_response"}.issubset(schema)


def test_security_pipeline_passes_sender_to_classifier_whitelist(tmp_path, monkeypatch):
    from agents.email_intelligence_agent.tools import _run_security_pipeline
    from security.pipeline.classifier import Classifier

    _setup_audit_dir(tmp_path, monkeypatch)
    whitelist = tmp_path / "sender-whitelist.yaml"
    whitelist.write_text(
        "email_overrides:\n"
        "  news@mail.fineconews.com:\n"
        "    domain: finance\n"
        "    confidence: 0.95\n"
        "domain_overrides: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Classifier, "_WHITELIST_PATH", whitelist)

    result = _run_security_pipeline(
        email_id="pm-whitelist",
        account="protonmail",
        sender='"FinecoBank" <news@mail.fineconews.com>',
        subject="Educazione finanziaria e strumenti",
        body="Contenuto informativo generico.",
    )

    assert result["classification"]["primary_domain"] == "finance"
    assert result["classification"]["confidence"] == 0.95


def test_action_hint_archives_social_notifications():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": '"LinkedIn" <invitations@linkedin.com>',
        "subject": "Voglio collegarmi",
        "body_redacted": "Un contatto LinkedIn e in attesa della tua risposta.",
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "general",
            "sensitivity": "public",
            "risk_level": "low",
            "priority": "normal",
            "confidence": 0.0,
        },
    }

    assert _compute_action_hint(payload) == "archive"


def test_action_hint_uses_body_for_action_required_tasks():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "no-reply@joindeleteme.com",
        "subject": "Your Next DeleteMe Privacy Report is Ready!",
        "body_redacted": "ACTION MAY BE REQUIRED BY YOU. Some brokers may require confirmation.",
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "general",
            "sensitivity": "internal",
            "risk_level": "medium",
            "priority": "normal",
            "confidence": 0.2,
        },
    }

    assert _compute_action_hint(payload) == "create_task"


def test_action_hint_archives_known_marketing_even_when_classifier_overstates_risk():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "Proton Meet meet@proton.me",
        "subject": "Proton Meet is here: Try it free now",
        "body_redacted": "Try Proton Meet for free today. Marketing newsletter from Proton.",
        "policy": {"decision": "reroute", "allow": True},
        "security_signals": {
            "prompt_injection_risk": "none",
            "suspicious_links": [],
            "blocked_attachments": [],
        },
        "classification": {
            "primary_domain": "legal",
            "secondary_domain": "marketing",
            "sensitivity": "sensitive",
            "risk_level": "high",
            "priority": "high",
            "confidence": 0.4,
        },
    }

    assert _compute_action_hint(payload) == "archive"


def test_action_hint_archives_whoop_security_alerts():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "support@whoop.com",
        "subject": "New Sign-In Alert - Was This You?",
        "body_redacted": "We noticed a new sign-in to your WHOOP account.",
        "policy": {"decision": "reroute", "allow": True},
        "security_signals": {
            "prompt_injection_risk": "none",
            "suspicious_links": [],
            "blocked_attachments": [],
        },
        "classification": {
            "primary_domain": "general",
            "sensitivity": "critical",
            "risk_level": "critical",
            "priority": "urgent",
            "confidence": 0.0,
        },
    }

    assert _compute_action_hint(payload) == "archive"


def test_action_hint_keeps_aruba_spid_events_for_cos():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "Aruba ID <comunicazioni@staff.aruba.it>",
        "subject": "SPID Aruba ID - Modifica la tua password",
        "body_redacted": "(empty body)",
        "policy": {"decision": "allow", "allow": True},
        "security_signals": {
            "prompt_injection_risk": "none",
            "suspicious_links": [],
            "blocked_attachments": [],
        },
        "classification": {
            "primary_domain": "notification",
            "sensitivity": "critical",
            "risk_level": "critical",
            "priority": "urgent",
            "confidence": 0.0,
        },
    }

    assert _compute_action_hint(payload) == "forward_to_cos"


def test_action_hint_does_not_create_task_for_unparsed_amex_confirmation():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "American Express <AmericanExpress@welcome.americanexpress.com>",
        "subject": "Conferma Operazione",
        "body_redacted": "(empty body)",
        "policy": {"decision": "allow", "allow": True},
        "security_signals": {
            "prompt_injection_risk": "none",
            "suspicious_links": [],
            "blocked_attachments": [],
        },
        "classification": {
            "primary_domain": "general",
            "sensitivity": "public",
            "risk_level": "low",
            "priority": "normal",
            "confidence": 0.0,
        },
    }

    assert _compute_action_hint(payload) == "archive"


def test_action_hint_archives_io_login_notifications():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "IO - l'app dei servizi pubblici <noreply@io.italia.it>",
        "subject": "È stato eseguito l'accesso sull'app IO",
        "body_redacted": "(empty body)",
        "policy": {"decision": "allow", "allow": True},
        "security_signals": {
            "prompt_injection_risk": "none",
            "suspicious_links": [],
            "blocked_attachments": [],
        },
        "classification": {
            "primary_domain": "notification",
            "sensitivity": "public",
            "risk_level": "low",
            "priority": "normal",
            "confidence": 0.0,
        },
    }

    assert _compute_action_hint(payload) == "archive"


def test_action_hint_archives_cloudflare_certificate_transparency_notifications():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "Cloudflare <noreply@cloudflare.com>",
        "subject": "Certificate transparency monitoring for prova9x.com",
        "body_redacted": "A certificate has been logged for prova9x.com.",
        "policy": {"decision": "allow", "allow": True},
        "security_signals": {
            "prompt_injection_risk": "none",
            "suspicious_links": [],
            "blocked_attachments": [],
        },
        "classification": {
            "primary_domain": "notification",
            "sensitivity": "public",
            "risk_level": "low",
            "priority": "normal",
            "confidence": 0.0,
        },
    }

    assert _compute_action_hint(payload) == "archive"


def test_action_hint_routes_cloudflare_service_problems_to_cio():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "Cloudflare <noreply@cloudflare.com>",
        "subject": "Cloudflare service problem detected",
        "body_redacted": "Origin error rate is elevated for prova9x.com.",
        "policy": {"decision": "allow", "allow": True},
        "security_signals": {
            "prompt_injection_risk": "none",
            "suspicious_links": [],
            "blocked_attachments": [],
        },
        "classification": {
            "primary_domain": "infrastructure",
            "sensitivity": "internal",
            "risk_level": "medium",
            "priority": "high",
            "confidence": 0.5,
        },
    }

    assert _compute_action_hint(payload) == "forward_to_cio"


def test_action_hint_creates_task_for_gse_fiscal_notice():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "GSE <noreply@gse.it>",
        "subject": "Comunicazione Redditi diversi 2025",
        "body_redacted": "(empty body)",
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "general",
            "sensitivity": "internal",
            "risk_level": "low",
            "priority": "normal",
            "confidence": 0.0,
        },
    }

    assert _compute_action_hint(payload) == "create_task"


def test_action_hint_creates_task_for_health_exam_notice():
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = {
        "sender": "emiliano.paluzzi@leonardo.com",
        "subject": "I: Esami Paluzzi",
        "body_redacted": "In allegato referti esami del sangue.",
        "policy": {"decision": "allow", "allow": True},
        "classification": {
            "primary_domain": "general",
            "sensitivity": "confidential",
            "risk_level": "medium",
            "priority": "normal",
            "confidence": 0.1,
        },
    }

    assert _compute_action_hint(payload) == "create_task"


def test_mt_digest_prompt_handles_forward_to_cio():
    from agents.mt.config import MT_BUILTIN_CRONS

    digest_prompt = next(cron["prompt"] for cron in MT_BUILTIN_CRONS if cron["name"] == "digest_poll")

    assert "'forward_to_cio'" in digest_prompt
    assert "send_message(to='cio'" in digest_prompt


def test_sorting_rules_archive_deescalated_notification_senders():
    sys.path.insert(0, str(Path(__file__).parent.parent / "vendor" / "mailctl" / "src"))
    from mailctl.sorting import evaluate_rules

    rules_path = Path(__file__).parent.parent / "src" / "agents" / "cos" / "sorting_rules.yaml"

    assert evaluate_rules(
        {"sender": "support@whoop.com", "subject": "New Sign-In Alert", "body": ""},
        rules_path,
    ) == "Archive"
    assert evaluate_rules(
        {"sender": "Cloudflare <noreply@cloudflare.com>", "subject": "Certificate transparency monitoring", "body": ""},
        rules_path,
    ) == "Archive"
    assert evaluate_rules(
        {"sender": "IO <noreply@io.italia.it>", "subject": "È stato eseguito l'accesso sull'app IO", "body": ""},
        rules_path,
    ) == "Archive"


def test_write_to_digest_deduplicates_by_account_email_and_received_at(tmp_path):
    from agents.email_intelligence_agent.tools import _write_to_digest

    digest = tmp_path / "mt_digest.json"
    entry = {
        "account": "protonmail",
        "email_id": "pm-1",
        "received_at": "2026-04-30T08:00:00+00:00",
        "mt_action_hint": "archive",
    }

    _write_to_digest(entry, digest)
    _write_to_digest({**entry, "subject": "duplicate"}, digest)

    lines = digest.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["email_id"] == "pm-1"


def test_write_to_digest_applies_retention_limit(tmp_path, monkeypatch):
    from agents.email_intelligence_agent.tools import _write_to_digest

    monkeypatch.setenv("MT_DIGEST_MAX_LINES", "2")
    digest = tmp_path / "mt_digest.json"

    for idx in range(3):
        _write_to_digest(
            {
                "account": "protonmail",
                "email_id": f"pm-{idx}",
                "received_at": f"2026-04-30T08:0{idx}:00+00:00",
            },
            digest,
        )

    email_ids = [json.loads(line)["email_id"] for line in digest.read_text(encoding="utf-8").splitlines()]
    assert email_ids == ["pm-1", "pm-2"]


def test_mt_sort_email_uses_gmx_endpoint_for_gmx_payload(monkeypatch):
    import agents.mt.email_sorter as sorter_mod

    calls = []

    class _Process:
        returncode = 0
        stdout = json.dumps({"sorted": True, "folder": "Archive"})
        stderr = ""

    def _run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Process()

    monkeypatch.setattr(sorter_mod.subprocess, "run", _run)

    result = sorter_mod.sort_email("gmx-42", {"account": "gmx", "subject": "Newsletter"})

    assert result["sorted"] is True
    assert calls[0][0] == ["mailctl", "sort", "--account", "gmx", "--uid", "42", "--json"]


def test_draft_reply_creates_pending_draft_without_marking_processed(tmp_path):
    from agents.mt.tools import create_mt_mcp_server

    server = create_mt_mcp_server(tmp_path)
    draft_reply = _tool(server, "draft_reply").fn

    response = asyncio.run(
        draft_reply({
            "email_id": "pm-draft-1",
            "subject": "Pranzo domani?",
            "sender": "person@example.com",
            "body_redacted": "Ti va di pranzare domani?",
            "draft_instructions": "tono cordiale",
        })
    )

    assert "draft_pending" in response["content"][0]["text"]
    assert not (tmp_path / "processed_ids.txt").exists()

    status = json.loads((tmp_path / "drafts" / "draft_status.json").read_text(encoding="utf-8"))
    assert status["pm-draft-1"]["status"] == "draft_pending"


def test_quarantine_email_uses_mailctl_move(tmp_path, monkeypatch):
    import subprocess as subprocess_mod
    from agents.email_intelligence_agent.tools import create_email_intelligence_mcp_server

    _setup_audit_dir(tmp_path, monkeypatch)

    calls = []

    class _Process:
        returncode = 0
        stdout = json.dumps({"moved": True})
        stderr = ""

    def _run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Process()

    monkeypatch.setattr(subprocess_mod, "run", _run)
    server = create_email_intelligence_mcp_server(tmp_path)
    quarantine = _tool(server, "quarantine_email").fn

    response = asyncio.run(
        quarantine({
            "email_id": "gmx-42",
            "account": "gmx",
            "reason": "malicious",
        })
    )

    assert "quarantined" in response["content"][0]["text"]
    assert calls[0][0] == [
        "mailctl",
        "move",
        "--account",
        "gmx",
        "--uid",
        "42",
        "--destination",
        "Quarantine",
        "--json",
    ]


def test_process_email_uses_html_text_when_body_is_empty(tmp_path, monkeypatch):
    """HTML-only AmEx messages must not enter the pipeline as '(empty body)'."""
    from agents.email_intelligence_agent import tools as eia_tools
    from agents.email_intelligence_agent.tools import create_email_intelligence_mcp_server

    digest_path = tmp_path / "mt_digest.json"
    monkeypatch.setenv("MT_DIGEST_PATH", str(digest_path))

    class _Process:
        returncode = 0
        stdout = "Conferma Operazione\n6 mag 2026 ESSELUNGA €42,10\n"
        stderr = ""

    def _run(cmd, **kwargs):
        assert cmd == ["html-text", "extract", "-", "--format", "text"]
        assert b"ESSELUNGA" in kwargs["input"]
        return _Process()

    captured = {}

    def _pipeline(**kwargs):
        captured["pipeline_body"] = kwargs["body"]
        return {
            "email_id": kwargs["email_id"],
            "account": kwargs["account"],
            "sender": kwargs["sender"],
            "received_at": kwargs["received_at"],
            "subject": kwargs["subject"],
            "body_redacted": kwargs["body"],
            "classification": {
                "primary_domain": "finance",
                "sensitivity": "public",
                "risk_level": "low",
                "priority": "high",
                "confidence": 1.0,
                "ynab_account_id": "2609b853-bc94-4e26-bd97-6e1b81d17ead",
                "ynab_account_source": "static",
                "subject_must_match": "conferma operazione",
                "body_account_map": None,
            },
            "policy": {"decision": "allow", "allow": True, "constraints": []},
            "routing": {"route_to": "local", "reason": "test"},
            "redaction": {"applied": False, "items_redacted": []},
        }

    async def _dispatch(**kwargs):
        captured["dispatch_text"] = kwargs["email_text"]

    monkeypatch.setattr(eia_tools.subprocess, "run", _run)
    monkeypatch.setattr(eia_tools, "_run_security_pipeline", _pipeline)
    monkeypatch.setattr(eia_tools, "_dispatch_to_cfo_worker", _dispatch)

    server = create_email_intelligence_mcp_server(tmp_path)
    process_email = _tool(server, "process_email").fn

    response = asyncio.run(
        process_email({
            "email_id": "pm-amex-html",
            "account": "protonmail",
            "subject": "Conferma Operazione",
            "body": "",
            "html": "<html><body><p>6 mag 2026 ESSELUNGA €42,10</p></body></html>",
            "sender": "AmericanExpress@welcome.americanexpress.com",
            "received_at": "2026-05-06T18:00:00+00:00",
        })
    )

    assert response["content"][0]["text"]
    assert captured["pipeline_body"] == "Conferma Operazione\n6 mag 2026 ESSELUNGA €42,10"
    assert captured["dispatch_text"] == "Conferma Operazione\n6 mag 2026 ESSELUNGA €42,10"
    digest_entry = json.loads(digest_path.read_text(encoding="utf-8").splitlines()[0])
    assert digest_entry["mt_action_hint"] == "forward_to_cfo"


def test_email_text_from_parts_preserves_amex_details_when_html_text_drops_template(monkeypatch):
    """AmEx templates can hide the transaction table from generic html-text extraction."""
    from agents.email_intelligence_agent import tools as eia_tools
    from agents.email_intelligence_agent.tools import _email_text_from_parts

    amex_html = """
    <html><body>
      <table><tr><td>Conferma Operazione</td></tr></table>
      <table>
        <tr><td>Dettagli operazione</td></tr>
        <tr><td>6 mag 2026 EASYPARKITA</td></tr>
        <tr><td>EUR</td><td>€1,41</td></tr>
      </table>
      <p>Attenzione: Questa mail e una comunicazione di servizio.</p>
    </body></html>
    """

    class _Process:
        returncode = 0
        stdout = "Attenzione: Questa mail e una comunicazione di servizio.\n"
        stderr = ""

    monkeypatch.setattr(eia_tools.subprocess, "run", lambda *_args, **_kwargs: _Process())

    text = _email_text_from_parts("", amex_html)

    assert "Conferma Operazione" in text
    assert "6 mag 2026 EASYPARKITA €1,41" in text
