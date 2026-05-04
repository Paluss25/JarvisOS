import json
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from mailctl.models import AccountConfig

_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "protonmail": {
        "IMAP_HOST": "host.docker.internal",
        "IMAP_PORT": "11143",
        "IMAP_SECURE": "false",
        "SMTP_HOST": "host.docker.internal",
        "SMTP_PORT": "11025",
        "SMTP_SECURE": "false",
        "SMTP_STARTTLS": "false",
    },
    "gmx": {
        "IMAP_HOST": "imap.gmx.com",
        "IMAP_PORT": "993",
        "IMAP_SECURE": "true",
        "SMTP_HOST": "mail.gmx.com",
        "SMTP_PORT": "587",
        "SMTP_SECURE": "false",
        "SMTP_STARTTLS": "true",
    },
}


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _first(raw: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw and raw[name] is not None:
            return raw[name]
    raise KeyError(names[0])


def _account_from_mapping(name: str, raw: dict[str, Any]) -> AccountConfig:
    merged = {**_PROVIDER_DEFAULTS.get(name, {}), **raw}
    return AccountConfig(
        name=name,
        imap_host=str(_first(merged, "imap_host", "IMAP_HOST")),
        imap_port=int(_first(merged, "imap_port", "IMAP_PORT")),
        imap_secure=_bool(merged.get("imap_secure", merged.get("IMAP_SECURE")), False),
        imap_user=str(_first(merged, "imap_user", "IMAP_USER")),
        imap_pass=str(_first(merged, "imap_pass", "IMAP_PASS")),
        smtp_host=str(_first(merged, "smtp_host", "SMTP_HOST")),
        smtp_port=int(_first(merged, "smtp_port", "SMTP_PORT")),
        smtp_secure=_bool(merged.get("smtp_secure", merged.get("SMTP_SECURE")), False),
        smtp_starttls=_bool(merged.get("smtp_starttls", merged.get("SMTP_STARTTLS")), False),
        smtp_user=str(_first(merged, "smtp_user", "SMTP_USER")),
        smtp_pass=str(_first(merged, "smtp_pass", "SMTP_PASS")),
        smtp_from=str(_first(merged, "smtp_from", "SMTP_FROM")),
    )


def _load_from_json_env() -> dict[str, AccountConfig]:
    raw_json = os.environ.get("MAILCTL_ACCOUNTS_JSON", "").strip()
    if not raw_json:
        return {}
    parsed = json.loads(raw_json)
    return {name: _account_from_mapping(name, cfg) for name, cfg in parsed.items()}


def _load_from_config_dir() -> dict[str, AccountConfig]:
    config_dir = Path(os.environ.get("MAILCTL_CONFIG_DIR", "/home/paluss/docker/agents"))
    accounts: dict[str, AccountConfig] = {}
    for name in ("protonmail", "gmx"):
        path = config_dir / f".env.{name}"
        if path.exists():
            accounts[name] = _account_from_mapping(name, dict(dotenv_values(path)))
    return accounts


def load_accounts() -> dict[str, AccountConfig]:
    accounts = _load_from_json_env()
    accounts.update(_load_from_config_dir())
    return accounts


def load_one_account(name: str) -> AccountConfig:
    accounts = load_accounts()
    try:
        return accounts[name]
    except KeyError as exc:
        raise KeyError(f"Unknown account: {name}") from exc
