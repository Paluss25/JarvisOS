"""Unit tests for ContactsClient — mocks caldav.DAVClient."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

VCARD_TEMPLATE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\n"
    "UID:{uid}\r\n"
    "FN:{fn}\r\n"
    "EMAIL:{email}\r\n"
    "TEL:{tel}\r\n"
    "NOTE:{note}\r\n"
    "END:VCARD\r\n"
)


def _mock_contact(uid="uid-1", fn="Alice Example", email="alice@example.com", tel="+39123456", note=""):
    c = MagicMock()
    c.data = VCARD_TEMPLATE.format(uid=uid, fn=fn, email=email, tel=tel, note=note)
    c.url = f"https://cal.prova9x.com/paluss/Contatti/{uid}.vcf"
    return c


def _make_client(addressbook_name="Contatti"):
    from agents.mt.contacts_client import ContactsClient

    mock_ab = MagicMock()
    mock_ab.name = addressbook_name
    mock_ab.url = f"https://cal.prova9x.com/paluss/{addressbook_name}/"

    mock_principal = MagicMock()
    mock_principal.addressbooks.return_value = [mock_ab]

    mock_dav = MagicMock()
    mock_dav.principal.return_value = mock_principal

    with patch("agents.mt.contacts_client.caldav.DAVClient", return_value=mock_dav):
        client = ContactsClient(
            url="https://cal.prova9x.com",
            user="paluss",
            password="secret",
            addressbook_name=addressbook_name,
        )
        client._mock_ab = mock_ab
        client._mock_dav = mock_dav
    return client


# ---------------------------------------------------------------------------
# list_contacts
# ---------------------------------------------------------------------------

def test_list_contacts_returns_parsed_list():
    client = _make_client()
    contact = _mock_contact(uid="c-1", fn="Alice Example")
    client._mock_ab.vcard_objects.return_value = [contact]

    result = client.list_contacts()

    assert len(result) == 1
    assert result[0]["uid"] == "c-1"
    assert result[0]["fn"] == "Alice Example"


def test_list_contacts_returns_empty_when_none():
    client = _make_client()
    client._mock_ab.vcard_objects.return_value = []

    result = client.list_contacts()

    assert result == []


# ---------------------------------------------------------------------------
# search_contacts
# ---------------------------------------------------------------------------

def test_search_contacts_returns_matching():
    client = _make_client()
    contact = _mock_contact(uid="c-2", fn="Bob Builder", email="bob@example.com")
    client._mock_ab.vcard_objects.return_value = [contact]

    result = client.search_contacts("bob")

    assert len(result) == 1
    assert result[0]["fn"] == "Bob Builder"


def test_search_contacts_returns_empty_when_no_match():
    client = _make_client()
    contact = _mock_contact(uid="c-3", fn="Alice Example", email="alice@example.com")
    client._mock_ab.vcard_objects.return_value = [contact]

    result = client.search_contacts("zzznomatch")

    assert result == []


# ---------------------------------------------------------------------------
# get_contact
# ---------------------------------------------------------------------------

def test_get_contact_returns_dict_for_known_uid():
    client = _make_client()
    contact = _mock_contact(uid="c-4", fn="Carol Dev")
    client._mock_ab.vcard_by_uid.return_value = contact

    result = client.get_contact("c-4")

    assert result["uid"] == "c-4"
    assert result["fn"] == "Carol Dev"


def test_get_contact_raises_for_unknown_uid():
    import caldav.lib.error as caldav_error

    client = _make_client()
    client._mock_ab.vcard_by_uid.side_effect = caldav_error.NotFoundError("not found")

    with pytest.raises(ValueError, match="Contact not found"):
        client.get_contact("unknown-uid")


# ---------------------------------------------------------------------------
# update_contact
# ---------------------------------------------------------------------------

def test_update_contact_saves_modified_vcard():
    client = _make_client()
    contact = _mock_contact(uid="c-5", fn="Old Name")
    client._mock_ab.vcard_by_uid.return_value = contact

    client.update_contact("c-5", fn="New Name", email="new@example.com")

    contact.save.assert_called_once()
    assert "New Name" in contact.data


def test_update_contact_raises_for_unknown_uid():
    import caldav.lib.error as caldav_error

    client = _make_client()
    client._mock_ab.vcard_by_uid.side_effect = caldav_error.NotFoundError("not found")

    with pytest.raises(ValueError, match="Contact not found"):
        client.update_contact("unknown-uid", fn="X")


# ---------------------------------------------------------------------------
# delete_contact
# ---------------------------------------------------------------------------

def test_delete_contact_calls_delete():
    client = _make_client()
    contact = _mock_contact(uid="c-6")
    client._mock_ab.vcard_by_uid.return_value = contact

    client.delete_contact("c-6")

    contact.delete.assert_called_once()


def test_delete_contact_raises_for_unknown_uid():
    import caldav.lib.error as caldav_error

    client = _make_client()
    client._mock_ab.vcard_by_uid.side_effect = caldav_error.NotFoundError("not found")

    with pytest.raises(ValueError, match="Contact not found"):
        client.delete_contact("unknown-uid")


# ---------------------------------------------------------------------------
# addressbook name not found
# ---------------------------------------------------------------------------

def test_list_contacts_raises_when_addressbook_not_found():
    from agents.mt.contacts_client import ContactsClient

    mock_ab = MagicMock()
    mock_ab.name = "work"

    mock_principal = MagicMock()
    mock_principal.addressbooks.return_value = [mock_ab]

    mock_dav = MagicMock()
    mock_dav.principal.return_value = mock_principal

    with patch("agents.mt.contacts_client.caldav.DAVClient", return_value=mock_dav):
        client = ContactsClient("https://cal.prova9x.com", "paluss", "secret", "personal")

    with pytest.raises(ValueError, match="not found"):
        client.list_contacts()
