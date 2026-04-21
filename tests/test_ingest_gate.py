"""Tests for IngestGate (pipeline layer 1)."""

from security.pipeline.ingest_gate import IngestGate


def test_script_tags_stripped():
    gate = IngestGate()
    body = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
    result = gate.process(subject="Test", body=body)
    assert "<script>" not in result.sanitized_body
    assert "alert" not in result.sanitized_body
    assert "Hello" in result.sanitized_body


def test_punycode_link_flagged():
    gate = IngestGate()
    # xn--e1afmapc.com is punycode
    body = '<a href="http://xn--e1afmapc.com/login">Click here</a>'
    result = gate.process(subject="Login", body=body)
    assert len(result.suspicious_links) > 0
    assert "PUNYCODE_DOMAIN" in result.reasons
    assert result.safe is False


def test_shortener_link_flagged():
    gate = IngestGate()
    body = '<a href="https://bit.ly/abc123">Click here</a>'
    result = gate.process(subject="Click me", body=body)
    assert "URL_SHORTENER" in result.reasons
    assert result.safe is False


def test_exe_attachment_blocked():
    gate = IngestGate()
    attachments = [
        {"filename": "invoice.exe", "content_type": "application/octet-stream"}
    ]
    result = gate.process(subject="Invoice", body="Please see attached.", attachments=attachments)
    assert len(result.blocked_attachments) > 0
    assert result.attachment_risk == "critical"
    assert result.safe is False
