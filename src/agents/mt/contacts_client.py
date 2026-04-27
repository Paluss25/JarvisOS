"""CardDAV wrapper for Radicale contacts operations.

Synchronous API — call from async code via asyncio.to_thread().

Uses caldav.DAVClient.request() for raw HTTP because caldav 3.x does not
expose Principal.addressbooks() — address books live under the CardDAV
addressbook-home-set, which differs from the calendar-home-set.
"""
from __future__ import annotations

import uuid
from urllib.parse import urlparse, urljoin
from typing import Optional

import caldav
import vobject

_NS_CARDDAV = "urn:ietf:params:xml:ns:carddav"
_RT_ADDRESSBOOK = f"{{{_NS_CARDDAV}}}addressbook"

_PROPFIND_COLLECTIONS = (
    '<propfind xmlns="DAV:" xmlns:CR="urn:ietf:params:xml:ns:carddav">'
    "<prop><displayname/><resourcetype/></prop>"
    "</propfind>"
)
_PROPFIND_HREFS = (
    '<propfind xmlns="DAV:"><prop><getetag/></prop></propfind>'
)


class ContactsClient:
    """Thin wrapper around caldav.DAVClient targeting a single Radicale address book."""

    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        addressbook_name: str = "",
    ) -> None:
        self._base_url = url.rstrip("/")
        self._user = user
        self._client = caldav.DAVClient(url=url, username=user, password=password)
        self._addressbook_name = addressbook_name
        self._addressbook_url: Optional[str] = None

    def _get_addressbook_url(self) -> str:
        if self._addressbook_url is not None:
            return self._addressbook_url

        principal_url = f"{self._base_url}/{self._user}/"
        resp = self._client.request(
            principal_url,
            method="PROPFIND",
            headers={"Depth": "1", "Content-Type": "application/xml"},
            body=_PROPFIND_COLLECTIONS,
        )
        results = resp.parse_propfind()

        books = []
        for r in results:
            rt = r.properties.get("{DAV:}resourcetype", [])
            if _RT_ADDRESSBOOK in rt:
                name = r.properties.get("{DAV:}displayname", "")
                books.append({"name": name, "href": r.href})

        if not books:
            raise ValueError("No address books found in Radicale principal.")

        if not self._addressbook_name:
            self._addressbook_url = self._base_url + books[0]["href"]
        else:
            matched = next(
                (b for b in books if b["name"].lower() == self._addressbook_name.lower()),
                None,
            )
            if matched is None:
                names = [b["name"] for b in books]
                raise ValueError(
                    f"Address book '{self._addressbook_name}' not found. Available: {names}"
                )
            self._addressbook_url = self._base_url + matched["href"]

        if not self._addressbook_url.endswith("/"):
            self._addressbook_url += "/"
        return self._addressbook_url

    def _list_vcf_hrefs(self) -> list[str]:
        ab_url = self._get_addressbook_url()
        resp = self._client.request(
            ab_url,
            method="PROPFIND",
            headers={"Depth": "1", "Content-Type": "application/xml"},
            body=_PROPFIND_HREFS,
        )
        results = resp.parse_propfind()
        return [r.href for r in results if r.href.endswith(".vcf")]

    def _fetch_vcard(self, href: str) -> str:
        resp = self._client.request(self._base_url + href, method="GET")
        return resp.raw

    def _vcard_url(self, uid: str) -> str:
        return self._get_addressbook_url() + uid + ".vcf"

    def list_contacts(self) -> list[dict]:
        hrefs = self._list_vcf_hrefs()
        contacts = []
        for href in hrefs:
            raw = self._fetch_vcard(href)
            contacts.append(_parse_contact(raw))
        return contacts

    def search_contacts(self, query: str) -> list[dict]:
        all_contacts = self.list_contacts()
        q = query.lower()
        return [
            c for c in all_contacts
            if q in c.get("fn", "").lower() or q in c.get("email", "").lower()
        ]

    def get_contact(self, uid: str) -> dict:
        href = f"/{self._user}/{self._get_addressbook_url().split('/')[-2]}/{uid}.vcf"
        resp = self._client.request(self._base_url + href, method="GET")
        if resp.status == 404:
            raise ValueError(f"Contact not found: {uid}")
        return _parse_contact(resp.raw)

    def update_contact(
        self,
        uid: str,
        fn: str,
        email: str = "",
        tel: str = "",
        note: str = "",
    ) -> None:
        # Verify the contact exists first
        href = f"/{self._user}/{self._get_addressbook_url().split('/')[-2]}/{uid}.vcf"
        check = self._client.request(self._base_url + href, method="GET")
        if check.status == 404:
            raise ValueError(f"Contact not found: {uid}")
        vcard_data = _build_vcard(uid, fn, email, tel, note)
        self._client.request(
            self._base_url + href,
            method="PUT",
            headers={"Content-Type": "text/vcard; charset=utf-8"},
            body=vcard_data,
        )

    def delete_contact(self, uid: str) -> None:
        href = f"/{self._user}/{self._get_addressbook_url().split('/')[-2]}/{uid}.vcf"
        check = self._client.request(self._base_url + href, method="GET")
        if check.status == 404:
            raise ValueError(f"Contact not found: {uid}")
        self._client.request(self._base_url + href, method="DELETE")


def _parse_contact(raw: str) -> dict:
    """Parse a vCard string into a plain dict."""
    vcard = vobject.readOne(raw)
    return {
        "uid": str(vcard.uid.value) if hasattr(vcard, "uid") else "",
        "fn": str(vcard.fn.value) if hasattr(vcard, "fn") else "",
        "email": str(vcard.email.value) if hasattr(vcard, "email") else "",
        "tel": str(vcard.tel.value) if hasattr(vcard, "tel") else "",
        "note": str(vcard.note.value) if hasattr(vcard, "note") else "",
    }


def _build_vcard(uid: str, fn: str, email: str, tel: str, note: str) -> str:
    """Build a minimal vCard 3.0 string."""
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"UID:{uid}",
        f"FN:{fn}",
    ]
    if email:
        lines.append(f"EMAIL:{email}")
    if tel:
        lines.append(f"TEL:{tel}")
    if note:
        lines.append(f"NOTE:{note}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"
