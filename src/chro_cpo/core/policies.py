from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PolicyDecision:
    allow_response: bool
    human_review_required: bool
    reason: str


class PolicyChecker:
    def evaluate_risk(self, risk: str) -> PolicyDecision:
        if risk in {"high", "critical"}:
            return PolicyDecision(False, True, f"risk level {risk} requires human review")
        return PolicyDecision(True, False, "direct response allowed")
