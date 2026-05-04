import smtplib
from contextlib import contextmanager
from email.message import EmailMessage

from mailctl.models import AccountConfig


@contextmanager
def smtp_connect(account: AccountConfig):
    cls = smtplib.SMTP_SSL if account.smtp_secure else smtplib.SMTP
    server = cls(account.smtp_host, account.smtp_port)
    if account.smtp_starttls:
        server.starttls()
    server.login(account.smtp_user, account.smtp_pass)
    try:
        yield server
    finally:
        try:
            server.quit()
        except Exception:
            pass


def build_message(account: AccountConfig, to: list[str], subject: str, body: str, cc: list[str] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = account.smtp_from
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def build_reply_message(account: AccountConfig, original: dict, body: str, reply_all: bool = False) -> EmailMessage:
    subject = str(original.get("subject", ""))
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    to = [str(original.get("from", "")).strip()]
    msg = build_message(account, to=to, subject=subject, body=body)
    message_id = str(original.get("message_id", "")).strip()
    references = str(original.get("references", "")).strip()
    if message_id:
        msg["In-Reply-To"] = message_id
        msg["References"] = f"{references} {message_id}".strip() if references else message_id
    return msg


def send_message(account: AccountConfig, to: list[str], subject: str, body: str, cc: list[str] | None = None) -> dict:
    msg = build_message(account, to, subject, body, cc)
    recipients = to + (cc or [])
    with smtp_connect(account) as server:
        server.send_message(msg, from_addr=account.smtp_from, to_addrs=recipients)
    return {"account": account.name, "sent": True, "to": to, "cc": cc or [], "subject": subject}


def send_reply(account: AccountConfig, original: dict, body: str, reply_all: bool = False) -> dict:
    msg = build_reply_message(account, original=original, body=body, reply_all=reply_all)
    recipients = [msg["To"]]
    with smtp_connect(account) as server:
        server.send_message(msg, from_addr=account.smtp_from, to_addrs=recipients)
    return {"account": account.name, "sent": True, "to": recipients, "subject": msg["Subject"], "reply_uid": original.get("uid")}
