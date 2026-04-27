"""CardDAV wrapper for Radicale contacts operations.

Synchronous API — call from async code via asyncio.to_thread().
"""
from __future__ import annotations

import uuid
from typing import Optional

import caldav
import caldav.lib.error
import vobject


class ContactsClient:
    """Thin wrapper around caldav.DAVClient targeting a single Radicale address book."""

    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        addressbook_name: str = "",
    ) -> None:
        self._client = caldav.DAVClient(url=url, username=user, password=password)
        self._addressbook_name = addressbook_name
        self._addressbook: Optional[object] = None

    def _get_addressbook(self):
        if self._addressbook is not None:
            return self._addressbook
        principal = self._client.principal()
        books = principal.addressbooks()
        if not books:
            raise ValueError("No address books found in Radicale principal.")
        if not self._addressbook_name:
            self._addressbook = books[0]
        else:
            for book in books:
                if (book.name or "").lower() == self._addressbook_name.lower():
                    self._addressbook = book
                    break
            if self._addressbook is None:
                names = [b.name for b in books]
                raise ValueError(
                    f"Address book '{self._addressbook_name}' not found. Available: {names}"
                )
        return self._addressbook

    def list_contacts(self) -> list[dict]:
        book = self._get_addressbook()
        contacts = book.vcard_objects()
        return [_parse_contact(c) for c in contacts]

    def search_contacts(self, query: str) -> list[dict]:
        book = self._get_addressbook()
        contacts = book.vcard_objects()
        q = query.lower()
        result = []
        for c in contacts:
            parsed = _parse_contact(c)
            if q in parsed.get("fn", "").lower() or q in parsed.get("email", "").lower():
                result.append(parsed)
        return result

    def get_contact(self, uid: str) -> dict:
        book = self._get_addressbook()
        try:
            contact = book.vcard_by_uid(uid)
        except caldav.lib.error.NotFoundError as exc:
            raise ValueError(f"Contact not found: {uid}") from exc
        return _parse_contact(contact)

    def update_contact(
        self,
        uid: str,
        fn: str,
        email: str = "",
        tel: str = "",
        note: str = "",
    ) -> None:
        book = self._get_addressbook()
        try:
            contact = book.vcard_by_uid(uid)
        except caldav.lib.error.NotFoundError as exc:
            raise ValueError(f"Contact not found: {uid}") from exc
        contact.data = _build_vcard(uid, fn, email, tel, note)
        contact.save()

    def delete_contact(self, uid: str) -> None:
        book = self._get_addressbook()
        try:
            contact = book.vcard_by_uid(uid)
        except caldav.lib.error.NotFoundError as exc:
            raise ValueError(f"Contact not found: {uid}") from exc
        contact.delete()


def _parse_contact(contact) -> dict:
    """Parse a caldav vcard object into a plain dict."""
    vcard = vobject.readOne(contact.data)
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
