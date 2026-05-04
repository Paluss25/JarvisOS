from typer.testing import CliRunner

from mailctl.cli import app


runner = CliRunner()


def test_accounts_command_with_no_config_dir(monkeypatch):
    monkeypatch.setenv("MAILCTL_CONFIG_DIR", "/tmp/mailctl-empty-config")
    monkeypatch.delenv("MAILCTL_ACCOUNTS_JSON", raising=False)

    result = runner.invoke(app, ["accounts", "--json"])

    assert result.exit_code == 0
    assert result.stdout.strip() == '{"accounts":[]}'
