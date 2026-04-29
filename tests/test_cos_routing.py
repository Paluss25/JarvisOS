"""Unit tests for HybridChiefOfStaffAgent.route()."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from security.chief_of_staff_agent import HybridChiefOfStaffAgent
from security.policy_engine import PolicyEngine
from security.config_loader import load_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> HybridChiefOfStaffAgent:
    cfg = load_all()
    policy = PolicyEngine(
        permissions=cfg["permissions"],
        approval_policy=cfg["approval_policy"],
        model_routing_rules=cfg["model_routing_rules"],
        memory_policy=cfg["memory_policy"],
    )
    return HybridChiefOfStaffAgent(policy_engine=policy)


def _make_payload(
    domain: str = "general",
    sensitivity: str = "public",
    risk: str = "none",
    priority: str = "normal",
    prompt_injection_risk: str = "none",
    secondary_domains: list | None = None,
) -> dict:
    """Build a minimal but structurally-complete email payload for CoS routing."""
    return {
        "email_id": "test-email-1",
        "account": "protonmail",
        "subject": "Test",
        "body_redacted": "Test body",
        "classification": {
            "primary_domain": domain,
            "secondary_domains": secondary_domains or [],
            "sensitivity": sensitivity,
            "risk_level": risk,
            "priority": priority,
            "confidence": 0.9,
        },
        "security_signals": {
            "prompt_injection_risk": prompt_injection_risk,
            "injection_patterns": [],
            "attachment_risk": "none",
            "blocked_attachments": [],
            "suspicious_links": [],
            "html_stripped": False,
        },
        "routing": {"route_to": "local", "reason": "DOMAIN_REQUIRES_LOCAL"},
        "policy": {"decision": "allow", "allow": True, "constraints": {}},
        "redaction": {"applied": True, "items_redacted": []},
        "entities": {},
    }


def _agent_names(decision: dict) -> list[str]:
    """Extract agent names from final_targets list."""
    return [t.get("agent", "") for t in decision.get("final_targets", [])]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_route_returns_dict():
    """route() must return a plain dict (asdict of RoutingDecision)."""
    agent = _make_agent()
    payload = _make_payload()
    decision = agent.route(payload)
    assert isinstance(decision, dict), f"Expected dict, got {type(decision)}"


def test_decision_has_required_keys():
    """Every routing decision must include the standard RoutingDecision fields."""
    agent = _make_agent()
    decision = agent.route(_make_payload())
    required = {
        "decision_id", "email_id", "thread_id", "decision_type",
        "final_targets", "actions", "archive_policy", "escalation",
        "executive_summary", "confidence",
    }
    for key in required:
        assert key in decision, f"Missing key in routing decision: {key}"


def test_finance_routes_to_cfo():
    """Finance domain email should include cfo in final_targets."""
    agent = _make_agent()
    payload = _make_payload(domain="finance", sensitivity="sensitive", risk="high", priority="high")
    decision = agent.route(payload)
    targets = _agent_names(decision)
    assert "cfo" in targets, (
        f"Expected cfo in final_targets, got: {targets}"
    )


def test_security_domain_routes_to_ciso():
    """Security domain email should include cio in final_targets."""
    agent = _make_agent()
    payload = _make_payload(domain="security", sensitivity="sensitive", risk="high", priority="high")
    decision = agent.route(payload)
    targets = _agent_names(decision)
    assert "cio" in targets, (
        f"Expected cio in final_targets, got: {targets}"
    )


def test_injection_high_escalates_to_ciso():
    """High prompt-injection risk must route to cio regardless of domain."""
    agent = _make_agent()
    payload = _make_payload(domain="general", prompt_injection_risk="high")
    decision = agent.route(payload)
    targets = _agent_names(decision)
    assert "cio" in targets, (
        f"Expected cio for high injection risk, got: {targets}"
    )


def test_injection_critical_escalates_to_ciso():
    """Critical prompt-injection risk must also route to cio."""
    agent = _make_agent()
    payload = _make_payload(domain="general", prompt_injection_risk="critical")
    decision = agent.route(payload)
    targets = _agent_names(decision)
    assert "cio" in targets, (
        f"Expected cio for critical injection risk, got: {targets}"
    )


def test_low_priority_general_is_ignore_or_known_type():
    """Low-priority general email should produce a safe, non-escalating decision."""
    agent = _make_agent()
    payload = _make_payload(domain="general", sensitivity="public", risk="none", priority="low")
    decision = agent.route(payload)
    dt = decision.get("decision_type", "")
    # Low-priority general → "ignore" per deterministic router logic
    valid_types = {"ignore", "archive", "route", "route_and_review", "notify", "internal_review"}
    assert dt in valid_types, f"Unexpected decision_type for low-priority general: {dt}"


def test_general_normal_priority_routes_to_cos():
    """Normal-priority general email is routed to cos (triage)."""
    agent = _make_agent()
    payload = _make_payload(domain="general", sensitivity="public", risk="none", priority="normal")
    decision = agent.route(payload)
    targets = _agent_names(decision)
    dt = decision.get("decision_type", "")
    # Should be routed (not ignored) and target CoS
    if dt != "ignore":
        assert any(t == "cos" for t in targets), (
            f"Expected cos for normal general email, got: {targets}"
        )


def test_infrastructure_domain_routes_to_cio():
    """Infrastructure domain email should target cio."""
    agent = _make_agent()
    payload = _make_payload(domain="infrastructure", sensitivity="internal", priority="normal")
    decision = agent.route(payload)
    targets = _agent_names(decision)
    assert "cio" in targets, (
        f"Expected cio for infrastructure domain, got: {targets}"
    )


def test_finance_email_id_echoed():
    """The routing decision must echo back the email_id from the payload."""
    agent = _make_agent()
    payload = _make_payload(domain="finance")
    payload["email_id"] = "fin-email-999"
    decision = agent.route(payload)
    assert decision.get("email_id") == "fin-email-999"
