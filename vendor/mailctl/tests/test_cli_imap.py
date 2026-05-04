import json
from unittest.mock import patch

from typer.testing import CliRunner

from mailctl.cli import app


runner = CliRunner()


def test_list_command_emits_compact_json(monkeypatch):
    monkeypatch.setenv("MAILCTL_CONFIG_DIR", "/tmp/mailctl-empty-config")
    monkeypatch.setenv(
        "MAILCTL_ACCOUNTS_JSON",
        json.dumps({
            "protonmail": {
                "imap_host": "imap.local",
                "imap_port": 143,
                "imap_user": "u",
                "imap_pass": "p",
                "smtp_host": "smtp.local",
                "smtp_port": 25,
                "smtp_user": "u",
                "smtp_pass": "p",
                "smtp_from": "u@example.com",
            }
        }),
    )

    with patch("mailctl.cli.list_emails_impl", return_value={"account": "protonmail", "folder": "INBOX", "total": 0, "emails": []}):
        result = runner.invoke(app, ["list", "--account", "protonmail", "--json"])

    assert result.exit_code == 0
    assert result.stdout.strip() == '{"account":"protonmail","folder":"INBOX","total":0,"emails":[]}'
