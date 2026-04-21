"""Layer 4 — RedactionEngine: PII and sensitive data redaction."""

from dataclasses import dataclass, field
from typing import List
import re


@dataclass
class RedactionResult:
    redacted_text: str
    redacted_items: List[str]   # names of PII types found and replaced
    redaction_applied: bool     # True if any redaction occurred


class RedactionEngine:
    _PATTERNS = [
        ("EMAIL",    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'),
        ("IBAN",     r'\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b'),
        ("PHONE",    r'(?:\+?\d[\d\s\-\(\)]{7,}\d)'),
        ("NAME_SALUTATION", r'\b(?:Dear|Hi|Hello|Ciao|Salve|Gentile)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b'),
        ("CREDENTIAL_TOKEN", r'\b(?:api[_\-]?key|token|secret|password|pwd)\s*[:=]\s*\S+'),
        ("IPV4",     r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
        ("ADDRESS",  r'\b\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Via|Piazza)\b'),
    ]
    _REPLACEMENT = "[REDACTED]"

    def redact(self, text: str) -> RedactionResult:
        redacted_items: List[str] = []
        result = text

        for name, pattern in self._PATTERNS:
            flags = re.IGNORECASE if name in ("CREDENTIAL_TOKEN", "ADDRESS") else 0
            new_result, count = re.subn(pattern, self._REPLACEMENT, result, flags=flags)
            if count > 0 and name not in redacted_items:
                redacted_items.append(name)
            result = new_result

        return RedactionResult(
            redacted_text=result,
            redacted_items=redacted_items,
            redaction_applied=len(redacted_items) > 0,
        )
