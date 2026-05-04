import json
from unittest.mock import patch

from typer.testing import CliRunner

from mailctl.cli import app


runner = CliRunner()


def _set_account(monkeypatch):
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


def test_sort_command_emits_json(monkeypatch, tmp_path):
    _set_account(monkeypatch)
    rules = tmp_path / "rules.yaml"
    rules.write_text("version: 1\nrules: []\n", encoding="utf-8")

    with patch("mailctl.cli.sort_email_impl", return_value={"account": "gmx", "uid": "42", "sorted": False, "reason": "no_rule_matched"}):
        result = runner.invoke(app, ["sort", "--account", "gmx", "--uid", "42", "--rules", str(rules), "--json"])

    assert result.exit_code == 0
    assert result.stdout.strip() == '{"account":"gmx","uid":"42","sorted":false,"reason":"no_rule_matched"}'
