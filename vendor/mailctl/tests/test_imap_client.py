from unittest.mock import MagicMock, patch

from mailctl.imap_client import list_emails, read_email
from mailctl.models import AccountConfig


def _account() -> AccountConfig:
    return AccountConfig(
        name="protonmail",
        imap_host="imap.local",
        imap_port=143,
        imap_secure=False,
        imap_user="u",
        imap_pass="p",
        smtp_host="smtp.local",
        smtp_port=25,
        smtp_user="u",
        smtp_pass="p",
        smtp_from="u@example.com",
    )


def test_list_emails_returns_metadata_only():
    client = MagicMock()
    client.uid.side_effect = [
        ("OK", [b"42"]),
        ("OK", [(b"42 (FLAGS (\\Seen) RFC822.HEADER {80})", b"From: A <a@example.com>\r\nSubject: Hi\r\nDate: Mon, 04 May 2026 10:00:00 +0000\r\n\r\n")]),
    ]

    with patch("imaplib.IMAP4", return_value=client):
        result = list_emails(_account(), folder="INBOX", limit=10, offset=0, unseen_only=True)

    assert result["account"] == "protonmail"
    assert result["emails"][0]["uid"] == "42"
    assert result["emails"][0]["subject"] == "Hi"
    assert result["emails"][0]["has_attachments"] is False
    assert "body" not in result["emails"][0]


def test_read_email_returns_body():
    raw = (
        b"From: A <a@example.com>\r\n"
        b"To: B <b@example.com>\r\n"
        b"Subject: Hi\r\n"
        b"Date: Mon, 04 May 2026 10:00:00 +0000\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Hello"
    )
    client = MagicMock()
    client.uid.return_value = ("OK", [(b"42 (FLAGS (\\Seen) RFC822 {120})", raw)])

    with patch("imaplib.IMAP4", return_value=client):
        result = read_email(_account(), uid="42", folder="INBOX")

    assert result["uid"] == "42"
    assert result["body"] == "Hello"
    assert result["attachments"] == []
