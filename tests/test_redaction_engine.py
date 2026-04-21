"""Tests for RedactionEngine (layer 4)."""

import pytest
from security.pipeline.redaction_engine import RedactionEngine, RedactionResult


def test_email_redacted():
    engine = RedactionEngine()
    result = engine.redact("Contact us at user@example.com for support")
    assert "[REDACTED]" in result.redacted_text
    assert "EMAIL" in result.redacted_items
    assert result.redaction_applied is True


def test_iban_redacted():
    result = RedactionEngine().redact("Wire funds to DE89370400440532013000")
    assert "[REDACTED]" in result.redacted_text
    assert "IBAN" in result.redacted_items


def test_credential_token_redacted():
    result = RedactionEngine().redact("api_key=sk-abc123xyz")
    assert "[REDACTED]" in result.redacted_text
    assert "CREDENTIAL_TOKEN" in result.redacted_items


def test_clean_text_unchanged():
    result = RedactionEngine().redact("Hello, please find the invoice attached.")
    assert result.redaction_applied is False
    assert result.redacted_items == []
