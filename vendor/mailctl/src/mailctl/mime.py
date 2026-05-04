import email
import email.header
import email.message
import email.policy
from typing import Optional


def decode_header_value(value: str) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded)


def parse_message(raw: bytes) -> email.message.EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)


def parse_body(msg: email.message.EmailMessage) -> tuple[Optional[str], Optional[str]]:
    plain = None
    html = None
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain" and plain is None:
                plain = part.get_content()
            elif content_type == "text/html" and html is None:
                html = part.get_content()
    elif msg.get_content_type() == "text/plain":
        plain = msg.get_content()
    elif msg.get_content_type() == "text/html":
        html = msg.get_content()
    return plain, html


def parse_attachments(msg: email.message.EmailMessage) -> list[dict]:
    attachments = []
    for part in msg.walk():
        if part.get_content_disposition() != "attachment":
            continue
        filename = part.get_filename() or "attachment"
        payload = part.get_payload(decode=True) or b""
        attachments.append({
            "index": len(attachments),
            "filename": decode_header_value(filename),
            "content_type": part.get_content_type(),
            "size_bytes": len(payload),
        })
    return attachments
