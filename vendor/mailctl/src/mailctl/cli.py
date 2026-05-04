import json
import sys
from pathlib import Path

import typer

from mailctl.config import load_accounts, load_one_account
from mailctl.imap_client import (
    list_emails as list_emails_impl,
    mark_email,
    move_email,
    read_email as read_email_impl,
    search_emails,
    unread_count,
)
from mailctl.safety import build_approval_preview, enforce_send_allowed
from mailctl.sorting import sort_email as sort_email_impl
from mailctl.smtp_client import send_message, send_reply

app = typer.Typer(no_args_is_help=True)


@app.callback()
def root() -> None:
    """Direct IMAP/SMTP email CLI."""


@app.command()
def accounts(json_output: bool = typer.Option(False, "--json")) -> None:
    payload = {"accounts": sorted(load_accounts())}
    _emit(payload, json_output)


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(payload, separators=(",", ":")))
        return
    typer.echo(json.dumps(payload, indent=2))


@app.command("list")
def list_command(
    account: str = typer.Option(..., "--account"),
    folder: str = typer.Option("INBOX", "--folder"),
    unread: bool = typer.Option(False, "--unread"),
    limit: int = typer.Option(20, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    payload = list_emails_impl(load_one_account(account), folder, limit, offset, unread)
    _emit(payload, json_output)


@app.command("read")
def read_command(
    account: str = typer.Option(..., "--account"),
    uid: str = typer.Option(..., "--uid"),
    folder: str = typer.Option("INBOX", "--folder"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    payload = read_email_impl(load_one_account(account), uid, folder)
    _emit(payload, json_output)


@app.command("unread-count")
def unread_count_command(
    account: str = typer.Option(..., "--account"),
    folder: list[str] = typer.Option(["INBOX"], "--folder"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _emit(unread_count(load_one_account(account), folder), json_output)


@app.command("search")
def search_command(
    account: str = typer.Option(..., "--account"),
    folder: str = typer.Option("INBOX", "--folder"),
    from_: str | None = typer.Option(None, "--from"),
    subject: str | None = typer.Option(None, "--subject"),
    body: str | None = typer.Option(None, "--body"),
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _emit(search_emails(load_one_account(account), folder=folder, from_=from_, subject=subject, body=body, limit=limit), json_output)


@app.command("mark")
def mark_command(
    account: str = typer.Option(..., "--account"),
    uid: str = typer.Option(..., "--uid"),
    folder: str = typer.Option("INBOX", "--folder"),
    read: bool = typer.Option(False, "--read"),
    unread: bool = typer.Option(False, "--unread"),
    flag: bool = typer.Option(False, "--flag"),
    unflag: bool = typer.Option(False, "--unflag"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    selected = [name for name, enabled in {"read": read, "unread": unread, "flag": flag, "unflag": unflag}.items() if enabled]
    if len(selected) != 1:
        raise typer.BadParameter("select exactly one mark action")
    _emit(mark_email(load_one_account(account), uid, folder, selected[0]), json_output)


@app.command("move")
def move_command(
    account: str = typer.Option(..., "--account"),
    uid: str = typer.Option(..., "--uid"),
    folder: str = typer.Option("INBOX", "--folder"),
    destination: str = typer.Option(..., "--destination", "--folder-to"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _emit(move_email(load_one_account(account), uid, folder, destination), json_output)


@app.command("sort")
def sort_command(
    account: str = typer.Option(..., "--account"),
    uid: str = typer.Option(..., "--uid"),
    folder: str = typer.Option("INBOX", "--folder"),
    rules: Path | None = typer.Option(None, "--rules"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _emit(sort_email_impl(load_one_account(account), uid=uid, source_folder=folder, rules_path=rules), json_output)


@app.command("draft-reply")
def draft_reply_command(
    account: str = typer.Option(..., "--account"),
    uid: str = typer.Option(..., "--uid"),
    body_file: Path = typer.Option(..., "--body-file"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    body = body_file.read_text(encoding="utf-8")
    _emit({"account": account, "uid": uid, "sent": False, "draft": body}, json_output)


@app.command("send")
def send_command(
    account: str = typer.Option(..., "--account"),
    to: list[str] = typer.Option(..., "--to"),
    subject: str = typer.Option(..., "--subject"),
    body_file: Path = typer.Option(..., "--body-file"),
    cc: list[str] = typer.Option([], "--cc"),
    hitl_token: str | None = typer.Option(None, "--hitl-token"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    cfg = load_one_account(account)
    body = body_file.read_text(encoding="utf-8")
    preview = build_approval_preview(account, cfg.smtp_from, to, cc, [], subject, body, [], None)
    enforce_send_allowed(preview, hitl_token=hitl_token, interactive=sys.stdin.isatty())
    _emit(send_message(cfg, to, subject, body, cc), json_output)


@app.command("reply")
def reply_command(
    account: str = typer.Option(..., "--account"),
    uid: str = typer.Option(..., "--uid"),
    folder: str = typer.Option("INBOX", "--folder"),
    body_file: Path = typer.Option(..., "--body-file"),
    hitl_token: str | None = typer.Option(None, "--hitl-token"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    cfg = load_one_account(account)
    body = body_file.read_text(encoding="utf-8")
    original = read_email_impl(cfg, uid=uid, folder=folder)
    preview = build_approval_preview(
        account,
        cfg.smtp_from,
        [original.get("from", "")],
        [],
        [],
        f"Re: {original.get('subject', '')}" if not str(original.get("subject", "")).lower().startswith("re:") else str(original.get("subject", "")),
        body,
        [],
        uid,
    )
    enforce_send_allowed(preview, hitl_token=hitl_token, interactive=sys.stdin.isatty())
    _emit(send_reply(cfg, original, body), json_output)


def main() -> None:
    app()
