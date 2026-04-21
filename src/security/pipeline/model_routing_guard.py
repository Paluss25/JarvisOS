"""Layer 5 — ModelRoutingGuard: route email processing to local or cloud model."""

from dataclasses import dataclass


@dataclass
class RoutingDecision:
    route_to: str        # "local" | "cloud"
    reason: str


class ModelRoutingGuard:
    _LOCAL_DOMAINS = frozenset({"finance", "legal", "security"})
    _LOCAL_SENSITIVITIES = frozenset({"sensitive", "critical"})

    def decide(
        self,
        primary_domain: str,
        sensitivity: str,
        redaction_applied: bool,
    ) -> RoutingDecision:
        if sensitivity in self._LOCAL_SENSITIVITIES:
            return RoutingDecision(route_to="local", reason="SENSITIVITY_REQUIRES_LOCAL")
        elif primary_domain in self._LOCAL_DOMAINS:
            return RoutingDecision(route_to="local", reason="DOMAIN_REQUIRES_LOCAL")
        elif not redaction_applied:
            return RoutingDecision(route_to="local", reason="NO_REDACTION_CLOUD_FORBIDDEN")
        else:
            return RoutingDecision(route_to="cloud", reason="LOW_RISK_REDACTED_CLOUD_ALLOWED")
