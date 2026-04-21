"""Tests for Classifier (pipeline layer 3)."""

from security.pipeline.classifier import Classifier


def test_finance_email():
    clf = Classifier()
    result = clf.classify(
        subject="Invoice payment due",
        body="Please wire the payment to our bank account IBAN DE89 3704 0044 0532 0130 00.",
    )
    assert result.primary_domain == "finance"
    assert result.sensitivity == "sensitive"   # "iban" keyword
    assert result.priority == "high"


def test_phishing_email():
    clf = Classifier()
    result = clf.classify(
        subject="Security breach detected",
        body=(
            "Your credential has been exposed. "
            "Ransomware attack ongoing. Malware deployed on firewall."
        ),
    )
    assert result.primary_domain == "security"
    assert result.risk_level in {"high", "critical"}


def test_newsletter():
    clf = Classifier()
    result = clf.classify(
        subject="Monthly Newsletter",
        body="Click to unsubscribe from our promotional campaign.",
    )
    assert result.primary_domain == "marketing"
    assert result.sensitivity == "public"


def test_general_fallback():
    clf = Classifier()
    result = clf.classify(
        subject="Hello",
        body="How are you doing today?",
    )
    assert result.primary_domain == "general"
    assert result.confidence < 0.3
