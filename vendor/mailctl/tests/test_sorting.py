from pathlib import Path
from unittest.mock import patch

from mailctl.models import AccountConfig
from mailctl.sorting import _default_rules_path, evaluate_rules, sort_email


def _account() -> AccountConfig:
    return AccountConfig(
        name="protonmail",
        imap_host="imap.local",
        imap_port=143,
        imap_user="u",
        imap_pass="p",
        smtp_host="smtp.local",
        smtp_port=25,
        smtp_user="u",
        smtp_pass="p",
        smtp_from="u@example.com",
    )


def test_evaluate_rules_matches_first_folder(tmp_path: Path):
    rules = tmp_path / "sorting_rules.yaml"
    rules.write_text(
        """
version: 1
rules:
  - name: Finance
    match: all
    conditions:
      subject_contains: fattura
      primary_domain: finance
    folder: Fatture
""".strip(),
        encoding="utf-8",
    )

    result = evaluate_rules(
        {
            "sender": "billing@example.com",
            "subject": "Nuova fattura",
            "body": "Totale 10 EUR",
            "classification": {"primary_domain": "finance"},
        },
        rules,
    )

    assert result == "Fatture"


def test_sort_email_moves_when_rule_matches(tmp_path: Path):
    rules = tmp_path / "sorting_rules.yaml"
    rules.write_text(
        """
version: 1
rules:
  - name: Receipts
    match: any
    conditions:
      subject_contains: receipt
    folder: Receipts
""".strip(),
        encoding="utf-8",
    )

    with patch("mailctl.sorting.read_email", return_value={"from": "a@example.com", "subject": "Receipt", "body": "Thanks"}), \
         patch("mailctl.sorting.move_email", return_value={"moved": True, "folder": "Receipts"}) as move:
        result = sort_email(_account(), uid="42", source_folder="INBOX", rules_path=rules)

    move.assert_called_once()
    assert result["sorted"] is True
    assert result["folder"] == "Receipts"


def test_default_rules_path_honors_env(monkeypatch, tmp_path: Path):
    rules = tmp_path / "sorting_rules.yaml"
    monkeypatch.setenv("MAILCTL_SORTING_RULES_PATH", str(rules))

    assert _default_rules_path() == rules
