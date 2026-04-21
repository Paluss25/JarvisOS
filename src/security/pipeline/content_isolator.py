"""Layer 2 — ContentIsolator: detect prompt-injection patterns in email content."""

import re
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class IsolationResult:
    safe: bool
    injection_patterns_found: List[str]
    risk_level: str  # "none" | "low" | "medium" | "high" | "critical"


# Patterns that auto-escalate to "critical" regardless of match count
_CRITICAL_PATTERNS = frozenset(
    {"CONTROL_TOKEN", "PRIVILEGE_ESCALATION", "JAILBREAK_KEYWORD", "DAN_MODE"}
)


class ContentIsolator:
    """Scan email text for LLM prompt-injection attempts."""

    _INJECTION_PATTERNS: List[Tuple[str, str]] = [
        (r"ignore\s+(all\s+)?previous\s+instructions?", "IGNORE_PREVIOUS_INSTRUCTIONS"),
        (r"you\s+are\s+now\s+(?:a|an)\s+\w+", "PERSONA_OVERRIDE"),
        (r"act\s+as\s+(?:a|an|if)\s+\w+", "ACT_AS_OVERRIDE"),
        (
            r"do\s+not\s+(?:follow|use|apply)\s+(?:your\s+)?(?:rules?|guidelines?|instructions?|policies?)",
            "RULE_BYPASS",
        ),
        (
            r"your\s+(?:new\s+)?(?:instructions?|prompt|system\s+prompt)\s+(?:is|are)\s*:",
            "SYSTEM_PROMPT_OVERRIDE",
        ),
        (r"print\s+(?:your\s+)?(?:system\s+)?prompt", "PROMPT_EXTRACTION"),
        (
            r"reveal\s+(?:your\s+)?(?:instructions?|prompt|configuration)",
            "CONFIG_EXTRACTION",
        ),
        (
            r"(?:what\s+are|show\s+me)\s+your\s+(?:instructions?|rules?|guidelines?)",
            "INSTRUCTION_EXTRACTION",
        ),
        (
            r"disregard\s+(?:all\s+)?(?:previous\s+)?(?:instructions?|rules?)",
            "DISREGARD_INSTRUCTIONS",
        ),
        (r"jailbreak", "JAILBREAK_KEYWORD"),
        (r"DAN\s+mode", "DAN_MODE"),
        (r"developer\s+mode", "DEVELOPER_MODE"),
        (r"enable\s+(?:admin|root|debug|override)\s+mode", "PRIVILEGE_ESCALATION"),
        (r"bypass\s+(?:security|filter|restriction|policy)", "SECURITY_BYPASS"),
        (r"<\|(?:system|endoftext|im_start|im_end)\|>", "CONTROL_TOKEN"),
    ]

    # Pre-compiled patterns (compiled once at class definition time)
    _COMPILED: List[Tuple[re.Pattern, str]] = [
        (re.compile(pattern, re.IGNORECASE), label)
        for pattern, label in _INJECTION_PATTERNS
    ]

    def check(self, text: str) -> IsolationResult:
        found: List[str] = []

        for compiled_re, label in self._COMPILED:
            if compiled_re.search(text):
                found.append(label)

        count = len(found)
        found_set = set(found)

        # Determine risk level
        if count == 0:
            risk_level = "none"
        elif count <= 2:
            risk_level = "low"
        elif count <= 4:
            risk_level = "medium"
        else:
            risk_level = "high"

        # Critical override — any single critical pattern escalates unconditionally
        if found_set & _CRITICAL_PATTERNS:
            risk_level = "critical"

        safe = risk_level in {"none", "low"}

        return IsolationResult(
            safe=safe,
            injection_patterns_found=found,
            risk_level=risk_level,
        )
