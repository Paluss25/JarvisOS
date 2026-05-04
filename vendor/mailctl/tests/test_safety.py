import json

from typer.testing import CliRunner

from mailctl.cli import app
from mailctl.safety import build_approval_preview, enforce_send_allowed


runner = CliRunner()


def test_enforce_send_allowed_blocks_agent_without_hitl(monkeypatch):
    monkeypatch.setenv("MAILCTL_AGENT_MODE", "1")
    preview = build_approval_preview(
        account="gmx",
        from_addr="u@example.com",
        to=["a@example.com"],
        cc=[],
        bcc=[],
        subject="Hello",
        body="Body",
        attachments=[],
        reply_uid=None,
    )

    try:
        enforce_send_allowed(preview, hitl_token=None, interactive=False)
    except PermissionError as exc:
        assert "HITL confirmation required" in str(exc)
    else:
        raise AssertionError("expected PermissionError")


def test_draft_reply_command_does_not_send(monkeypatch, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("Approved draft text", encoding="utf-8")
    result = runner.invoke(app, ["draft-reply", "--account", "protonmail", "--uid", "42", "--body-file", str(body_file), "--json"])
    assert result.exit_code == 0
    assert '"sent":false' in result.stdout


def test_send_command_blocks_in_agent_mode_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("MAILCTL_AGENT_MODE", "1")
    monkeypatch.setenv("MAILCTL_CONFIG_DIR", "/tmp/mailctl-empty-config")
    monkeypatch.setenv(
        "MAILCTL_ACCOUNTS_JSON",
        json.dumps({
            "gmx": {
                "imap_host": "imap.local",
                "imap_port": 993,
                "imap_secure": True,
                "imap_user": "u",
                "imap_pass": "p",
                "smtp_host": "smtp.local",
                "smtp_port": 587,
                "smtp_starttls": True,
                "smtp_user": "u",
                "smtp_pass": "p",
                "smtp_from": "u@example.com",
            }
        }),
    )
    body_file = tmp_path / "body.md"
    body_file.write_text("Body", encoding="utf-8")

    result = runner.invoke(app, ["send", "--account", "gmx", "--to", "a@example.com", "--subject", "Hello", "--body-file", str(body_file), "--json"])

    assert result.exit_code == 1
    assert "HITL confirmation required" in str(result.exception)
