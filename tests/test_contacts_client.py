"""Unit tests for ContactsClient — mocks caldav.DAVClient.request()."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

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


def _vcard(uid="uid-1", fn="Alice Example", email="alice@example.com", tel="+39123", note=""):
    return VCARD_TEMPLATE.format(uid=uid, fn=fn, email=email, tel=tel, note=note)


def _dav_resp(status=200, raw="", propfind_results=None):
    resp = MagicMock()
    resp.status = status
    resp.raw = raw
    if propfind_results is not None:
        resp.parse_propfind.return_value = propfind_results
    return resp


def _propfind_result(href, resourcetype=None, displayname=None):
    r = MagicMock()
    r.href = href
    r.properties = {}
    if resourcetype:
        r.properties["{DAV:}resourcetype"] = resourcetype
    if displayname is not None:
        r.properties["{DAV:}displayname"] = displayname
    return r


_AB_HREF = "/paluss/ab-uuid/"
_VCF1_HREF = "/paluss/ab-uuid/uid-1.vcf"
_VCF2_HREF = "/paluss/ab-uuid/uid-2.vcf"
_BASE = "https://cal.prova9x.com"
_AB_URL = _BASE + _AB_HREF
_NS_CARDDAV = "urn:ietf:params:xml:ns:carddav"


def _make_client(addressbook_name="Contatti"):
    """Build a ContactsClient with mocked caldav.DAVClient and pre-cached address book URL."""
    from agents.mt.contacts_client import ContactsClient

    mock_dav = MagicMock()
    with patch("agents.mt.contacts_client.caldav.DAVClient", return_value=mock_dav):
        client = ContactsClient(
            url=_BASE,
            user="paluss",
            password="secret",
            addressbook_name=addressbook_name,
        )
    # Pre-cache the address book URL so individual tests don't need to mock PROPFIND discovery
    client._addressbook_url = _AB_URL
    client._mock_dav = mock_dav
    return client


# ---------------------------------------------------------------------------
# list_contacts
# ---------------------------------------------------------------------------


def test_list_contacts_returns_parsed_list():
    client = _make_client()
    # PROPFIND returns two .vcf hrefs
    propfind_resp = _dav_resp(propfind_results=[
        _propfind_result(_AB_HREF),
        _propfind_result(_VCF1_HREF),
    ])
    get_resp = _dav_resp(raw=_vcard(uid="uid-1", fn="Alice Example"))
    client._mock_dav.request.side_effect = [propfind_resp, get_resp]

    result = client.list_contacts()

    assert len(result) == 1
    assert result[0]["uid"] == "uid-1"
    assert result[0]["fn"] == "Alice Example"


def test_list_contacts_returns_empty_when_none():
    client = _make_client()
    # PROPFIND returns only the collection itself (no .vcf files)
    propfind_resp = _dav_resp(propfind_results=[_propfind_result(_AB_HREF)])
    client._mock_dav.request.return_value = propfind_resp

    result = client.list_contacts()

    assert result == []


# ---------------------------------------------------------------------------
# search_contacts
# ---------------------------------------------------------------------------


def test_search_contacts_returns_matching():
    client = _make_client()
    propfind_resp = _dav_resp(propfind_results=[
        _propfind_result(_AB_HREF),
        _propfind_result(_VCF1_HREF),
    ])
    get_resp = _dav_resp(raw=_vcard(uid="uid-1", fn="Bob Builder", email="bob@example.com"))
    client._mock_dav.request.side_effect = [propfind_resp, get_resp]

    result = client.search_contacts("bob")

    assert len(result) == 1
    assert result[0]["fn"] == "Bob Builder"


def test_search_contacts_returns_empty_when_no_match():
    client = _make_client()
    propfind_resp = _dav_resp(propfind_results=[
        _propfind_result(_AB_HREF),
        _propfind_result(_VCF1_HREF),
    ])
    get_resp = _dav_resp(raw=_vcard(uid="uid-1", fn="Alice Example", email="alice@example.com"))
    client._mock_dav.request.side_effect = [propfind_resp, get_resp]

    result = client.search_contacts("zzznomatch")

    assert result == []


# ---------------------------------------------------------------------------
# get_contact
# ---------------------------------------------------------------------------


def test_get_contact_returns_dict_for_known_uid():
    client = _make_client()
    client._mock_dav.request.return_value = _dav_resp(raw=_vcard(uid="uid-4", fn="Carol Dev"))

    result = client.get_contact("uid-4")

    assert result["uid"] == "uid-4"
    assert result["fn"] == "Carol Dev"


def test_get_contact_raises_for_unknown_uid():
    client = _make_client()
    client._mock_dav.request.return_value = _dav_resp(status=404)

    with pytest.raises(ValueError, match="Contact not found"):
        client.get_contact("unknown-uid")


# ---------------------------------------------------------------------------
# update_contact
# ---------------------------------------------------------------------------


def test_update_contact_saves_modified_vcard():
    client = _make_client()
    existing = _dav_resp(raw=_vcard(uid="uid-5", fn="Old Name"))
    put_resp = _dav_resp(status=204)
    client._mock_dav.request.side_effect = [existing, put_resp]

    client.update_contact("uid-5", fn="New Name", email="new@example.com")

    # Second call should be PUT with the new vcard data in the body
    put_call = client._mock_dav.request.call_args_list[1]
    assert put_call.kwargs.get("method") == "PUT" or put_call.args[1] == "PUT"
    body = put_call.kwargs.get("body") or (put_call.args[2] if len(put_call.args) > 2 else "")
    assert "New Name" in body


def test_update_contact_raises_for_unknown_uid():
    client = _make_client()
    client._mock_dav.request.return_value = _dav_resp(status=404)

    with pytest.raises(ValueError, match="Contact not found"):
        client.update_contact("unknown-uid", fn="X")


# ---------------------------------------------------------------------------
# delete_contact
# ---------------------------------------------------------------------------


def test_delete_contact_calls_delete():
    client = _make_client()
    existing = _dav_resp(raw=_vcard(uid="uid-6"))
    del_resp = _dav_resp(status=204)
    client._mock_dav.request.side_effect = [existing, del_resp]

    client.delete_contact("uid-6")

    # Second call should be DELETE
    del_call = client._mock_dav.request.call_args_list[1]
    method = del_call.kwargs.get("method") or (del_call.args[1] if len(del_call.args) > 1 else "")
    assert method == "DELETE"


def test_delete_contact_raises_for_unknown_uid():
    client = _make_client()
    client._mock_dav.request.return_value = _dav_resp(status=404)

    with pytest.raises(ValueError, match="Contact not found"):
        client.delete_contact("unknown-uid")


# ---------------------------------------------------------------------------
# addressbook name not found (tests _get_addressbook_url)
# ---------------------------------------------------------------------------


def test_list_contacts_raises_when_addressbook_not_found():
    from agents.mt.contacts_client import ContactsClient

    mock_dav = MagicMock()
    propfind_resp = _dav_resp(propfind_results=[
        _propfind_result(
            "/paluss/work-ab/",
            resourcetype=[f"{{{_NS_CARDDAV}}}addressbook", "{DAV:}collection"],
            displayname="work",
        ),
    ])
    mock_dav.request.return_value = propfind_resp

    with patch("agents.mt.contacts_client.caldav.DAVClient", return_value=mock_dav):
        client = ContactsClient(_BASE, "paluss", "secret", addressbook_name="personal")

    with pytest.raises(ValueError, match="not found"):
        client.list_contacts()
