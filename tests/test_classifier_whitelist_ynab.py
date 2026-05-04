"""Tests: Classifier passes YNAB routing fields from sender-whitelist into ClassificationResult."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from security.pipeline.classifier import Classifier, ClassificationResult


_WHITELIST = {
    "email_overrides": {
        "no-reply@mediobancapremier.com": {
            "domain": "finance",
            "confidence": 1.0,
            "ynab_account_id": "e586d58c-bcac-48c6-848c-b219e00e0ea4",
            "subject_must_match": "mutuo|rata|addebito|bonifico|pagamento",
            "note": "test",
        },
        "assistenza@paypal.it": {
            "domain": "finance",
            "confidence": 1.0,
            "ynab_account_id": None,
            "ynab_account_source": "body_extract",
            "body_account_map": {
                "FINECO": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a",
                "AMEX": "2609b853-bc94-4e26-bd97-6e1b81d17ead",
            },
            "note": "test",
        },
    },
    "domain_overrides": {
        "@finecobank.com": {
            "domain": "finance",
            "confidence": 1.0,
            "ynab_account_id": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a",
            "note": "test",
        },
    },
}


def _make_classifier_with_whitelist(wl: dict) -> Classifier:
    """Return a Classifier that uses the given whitelist dict without touching disk."""
    c = Classifier()
    c._whitelist_data = wl
    c._whitelist_mtime = 1.0
    c._whitelist_checked_at = float("inf")  # prevent reload
    return c


def test_email_override_exposes_ynab_account_id():
    c = _make_classifier_with_whitelist(_WHITELIST)
    result = c.classify(
        subject="Rata mutuo",
        body="Addebito di € 1200 in data 01/05/2026",
        sender="no-reply@mediobancapremier.com",
    )
    assert isinstance(result, ClassificationResult)
    assert result.primary_domain == "finance"
    assert result.ynab_account_id == "e586d58c-bcac-48c6-848c-b219e00e0ea4"
    assert result.subject_must_match == "mutuo|rata|addebito|bonifico|pagamento"
    assert result.ynab_account_source == "static"
    assert result.body_account_map is None


def test_email_override_body_extract():
    c = _make_classifier_with_whitelist(_WHITELIST)
    result = c.classify(
        subject="Pagamento confermato",
        body="Hai pagato Apple Services con FINECO",
        sender="assistenza@paypal.it",
    )
    assert result.ynab_account_id is None
    assert result.ynab_account_source == "body_extract"
    assert result.body_account_map == {
        "FINECO": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a",
        "AMEX": "2609b853-bc94-4e26-bd97-6e1b81d17ead",
    }


def test_domain_override_exposes_ynab_account_id():
    c = _make_classifier_with_whitelist(_WHITELIST)
    result = c.classify(
        subject="Notifica bonifico",
        body="Hai ricevuto un bonifico di EUR 500",
        sender="noreply@finecobank.com",
    )
    assert result.ynab_account_id == "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a"
    assert result.subject_must_match is None
    assert result.ynab_account_source == "static"


def test_unmatched_sender_has_no_ynab_fields():
    c = _make_classifier_with_whitelist(_WHITELIST)
    result = c.classify(
        subject="Hello",
        body="Some general email",
        sender="stranger@example.com",
    )
    assert result.ynab_account_id is None
    assert result.subject_must_match is None
    assert result.ynab_account_source == "static"
    assert result.body_account_map is None
