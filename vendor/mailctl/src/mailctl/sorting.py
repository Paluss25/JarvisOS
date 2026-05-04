import fnmatch
import os
from pathlib import Path

import yaml

from mailctl.imap_client import move_email, read_email
from mailctl.models import AccountConfig


def _contains(value: str, expected: object) -> bool:
    haystack = value.lower()
    if isinstance(expected, list):
        return any(str(item).lower() in haystack for item in expected)
    return str(expected).lower() in haystack


def _condition_matches(email_data: dict, condition: str, expected: object) -> bool:
    if condition == "sender":
        return fnmatch.fnmatch(email_data.get("sender", "").lower(), str(expected).lower())
    if condition == "subject_contains":
        return _contains(email_data.get("subject", ""), expected)
    if condition == "body_contains":
        return _contains(email_data.get("body", ""), expected)
    classification = email_data.get("classification", {})
    if condition in {"primary_domain", "priority", "sensitivity"}:
        return str(classification.get(condition, "")).lower() == str(expected).lower()
    return False


def evaluate_rules(email_data: dict, rules_path: Path) -> str | None:
    data = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    for rule in data.get("rules", []):
        conditions = rule.get("conditions", {})
        mode = rule.get("match", "all")
        checks = [_condition_matches(email_data, key, value) for key, value in conditions.items()]
        matched = all(checks) if mode == "all" else any(checks)
        if matched:
            return str(rule["folder"])
    return None


def _default_rules_path() -> Path:
    configured = os.environ.get("MAILCTL_SORTING_RULES_PATH", "").strip()
    if configured:
        return Path(configured)
    for candidate in (
        Path("/app/src/agents/cos/sorting_rules.yaml"),
        Path("/home/paluss/docker/compose/jarvisOS/src/agents/cos/sorting_rules.yaml"),
    ):
        if candidate.exists():
            return candidate
    return Path("/app/src/agents/cos/sorting_rules.yaml")


def sort_email(account: AccountConfig, uid: str, source_folder: str = "INBOX", rules_path: Path | None = None) -> dict:
    rules_path = rules_path or _default_rules_path()
    if not rules_path.exists():
        return {"account": account.name, "uid": uid, "sorted": False, "reason": "rules_file_not_found"}
    message = read_email(account, uid=uid, folder=source_folder)
    target = evaluate_rules(
        {
            "sender": message.get("from", ""),
            "subject": message.get("subject", ""),
            "body": message.get("body", ""),
            "classification": message.get("classification", {}),
        },
        rules_path,
    )
    if target is None:
        return {"account": account.name, "uid": uid, "sorted": False, "reason": "no_rule_matched"}
    move_email(account, uid=uid, folder=source_folder, destination=target)
    return {"account": account.name, "uid": uid, "sorted": True, "folder": target}
