import json
from pathlib import Path

from mailctl.config import load_accounts, load_one_account


def test_load_accounts_from_json_env(monkeypatch):
    monkeypatch.setenv("MAILCTL_CONFIG_DIR", "/tmp/mailctl-empty-config")
    monkeypatch.setenv(
        "MAILCTL_ACCOUNTS_JSON",
        json.dumps({
            "protonmail": {
                "imap_host": "host.docker.internal",
                "imap_port": 11143,
                "imap_secure": False,
                "imap_user": "user@pm.me",
                "imap_pass": "imap-pass",
                "smtp_host": "host.docker.internal",
                "smtp_port": 11025,
                "smtp_secure": False,
                "smtp_starttls": False,
                "smtp_user": "user@pm.me",
                "smtp_pass": "smtp-pass",
                "smtp_from": "user@pm.me",
            }
        }),
    )

    accounts = load_accounts()

    assert list(accounts) == ["protonmail"]
    assert accounts["protonmail"].imap_port == 11143
    assert accounts["protonmail"].smtp_starttls is False


def test_load_one_account_rejects_missing_account(monkeypatch):
    monkeypatch.setenv("MAILCTL_CONFIG_DIR", "/tmp/mailctl-empty-config")
    monkeypatch.setenv("MAILCTL_ACCOUNTS_JSON", "{}")

    try:
        load_one_account("gmx")
    except KeyError as exc:
        assert "Unknown account: gmx" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_load_accounts_applies_provider_defaults(monkeypatch, tmp_path: Path):
    config_dir = tmp_path / "accounts"
    config_dir.mkdir()
    (config_dir / ".env.gmx").write_text(
        "IMAP_USER=gmx@example.com\n"
        "IMAP_PASS=imap-pass\n"
        "SMTP_USER=gmx@example.com\n"
        "SMTP_PASS=smtp-pass\n"
        "SMTP_FROM=gmx@example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAILCTL_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MAILCTL_ACCOUNTS_JSON", "{}")

    accounts = load_accounts()

    assert accounts["gmx"].imap_host == "imap.gmx.com"
    assert accounts["gmx"].imap_port == 993
    assert accounts["gmx"].smtp_host == "mail.gmx.com"
    assert accounts["gmx"].smtp_starttls is True
