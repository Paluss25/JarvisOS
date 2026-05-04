from unittest.mock import MagicMock, patch

from mailctl.imap_client import mark_email, move_email, search_emails, unread_count
from mailctl.models import AccountConfig


def _account() -> AccountConfig:
    return AccountConfig(
        name="gmx",
        imap_host="imap.local",
        imap_port=993,
        imap_secure=True,
        imap_user="u",
        imap_pass="p",
        smtp_host="smtp.local",
        smtp_port=587,
        smtp_starttls=True,
        smtp_user="u",
        smtp_pass="p",
        smtp_from="u@example.com",
    )


def test_mark_email_read_uses_seen_flag():
    client = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=client):
        result = mark_email(_account(), uid="42", folder="INBOX", action="read")
    client.uid.assert_called_with("STORE", "42", "+FLAGS", "(\\Seen)")
    assert result["marked"] == "read"


def test_move_email_copy_delete_expunge():
    client = MagicMock()
    with patch("imaplib.IMAP4_SSL", return_value=client):
        result = move_email(_account(), uid="42", folder="INBOX", destination="Archive")
    client.uid.assert_any_call("COPY", "42", "Archive")
    client.uid.assert_any_call("STORE", "42", "+FLAGS", "(\\Deleted)")
    client.expunge.assert_called_once()
    assert result["moved"] is True


def test_unread_count_parses_status_response():
    client = MagicMock()
    client.status.return_value = ("OK", [b'INBOX (UNSEEN 7)'])
    with patch("imaplib.IMAP4_SSL", return_value=client):
        result = unread_count(_account(), folders=["INBOX"])
    assert result["counts"]["INBOX"] == 7


def test_search_emails_uses_from_and_subject_criteria():
    client = MagicMock()
    client.uid.return_value = ("OK", [b"42"])
    with patch("imaplib.IMAP4_SSL", return_value=client):
        result = search_emails(_account(), folder="INBOX", from_="billing@example.com", subject="invoice", limit=10)
    client.uid.assert_called_with("SEARCH", 'FROM "billing@example.com" SUBJECT "invoice"')
    assert result["uids"] == ["42"]
