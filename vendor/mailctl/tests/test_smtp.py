from unittest.mock import MagicMock, patch

from mailctl.models import AccountConfig
from mailctl.smtp_client import build_reply_message, send_message


def _account() -> AccountConfig:
    return AccountConfig(
        name="gmx",
        imap_host="imap.local",
        imap_port=993,
        imap_secure=True,
        imap_user="u",
        imap_pass="imap-pass",
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_secure=False,
        smtp_starttls=True,
        smtp_user="u",
        smtp_pass="smtp-pass",
        smtp_from="u@example.com",
    )


def test_send_message_uses_starttls_before_login():
    server = MagicMock()

    with patch("smtplib.SMTP", return_value=server):
        result = send_message(_account(), ["to@example.com"], "Subject", "Body")

    server.starttls.assert_called_once()
    server.login.assert_called_once_with("u", "smtp-pass")
    server.send_message.assert_called_once()
    assert result["sent"] is True


def test_build_reply_message_addresses_original_sender():
    msg = build_reply_message(
        _account(),
        original={"from": "Alice <alice@example.com>", "subject": "Question", "message_id": "<m1@example.com>", "references": ""},
        body="Answer",
    )

    assert msg["To"] == "Alice <alice@example.com>"
    assert msg["Subject"] == "Re: Question"
    assert msg["In-Reply-To"] == "<m1@example.com>"
