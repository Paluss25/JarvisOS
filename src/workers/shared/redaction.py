"""PII redaction helper for jarvios-platform workers (P5.T3 mirror).

Mirrors `app.services.redaction` in cfo-data-service so any prompt
assembled inside a worker (investment-research, macro-scenario,
opportunity-scanner, etc.) is scrubbed of wallet addresses, IBANs,
codice fiscale, and personal email addresses before reaching the
Claude CLI subprocess.
"""

from __future__ import annotations

import re
from typing import Any

_EVM_ADDR_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_BTC_BECH32_RE = re.compile(r"\bbc1[a-z0-9]{6,87}\b", re.IGNORECASE)
_BTC_LEGACY_RE = re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")
_IBAN_RE = re.compile(
    r"\b[A-Z]{2}[0-9]{2}(?:[\s-]?[A-Z0-9]{4}){3,7}(?:[\s-]?[A-Z0-9]{1,4})?\b"
)
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b"
)
_CF_RE = re.compile(r"\b[A-Z]{6}[0-9]{2}[A-Z][0-9]{2}[A-Z][0-9]{3}[A-Z]\b")


def redact(value: Any) -> Any:
    """Recursively scrub PII from strings, dicts, lists, tuples."""
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def _redact_str(text: str) -> str:
    text = _EVM_ADDR_RE.sub("[REDACTED_EVM_ADDR]", text)
    text = _BTC_BECH32_RE.sub("[REDACTED_BTC_ADDR]", text)
    text = _BTC_LEGACY_RE.sub("[REDACTED_BTC_ADDR]", text)
    text = _IBAN_RE.sub("[REDACTED_IBAN]", text)
    text = _CF_RE.sub("[REDACTED_CF]", text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    return text
