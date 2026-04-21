"""Tests for ModelRoutingGuard (layer 5)."""

import pytest
from security.pipeline.model_routing_guard import ModelRoutingGuard, RoutingDecision


def test_sensitive_forces_local():
    guard = ModelRoutingGuard()
    d = guard.decide(primary_domain="general", sensitivity="sensitive", redaction_applied=True)
    assert d.route_to == "local"
    assert d.reason == "SENSITIVITY_REQUIRES_LOCAL"


def test_critical_sensitivity_forces_local():
    d = ModelRoutingGuard().decide(primary_domain="general", sensitivity="critical", redaction_applied=True)
    assert d.route_to == "local"
    assert d.reason == "SENSITIVITY_REQUIRES_LOCAL"


def test_finance_domain_forces_local():
    d = ModelRoutingGuard().decide(primary_domain="finance", sensitivity="public", redaction_applied=True)
    assert d.route_to == "local"
    assert d.reason == "DOMAIN_REQUIRES_LOCAL"


def test_legal_domain_forces_local():
    d = ModelRoutingGuard().decide(primary_domain="legal", sensitivity="public", redaction_applied=True)
    assert d.route_to == "local"
    assert d.reason == "DOMAIN_REQUIRES_LOCAL"


def test_security_domain_forces_local():
    d = ModelRoutingGuard().decide(primary_domain="security", sensitivity="public", redaction_applied=True)
    assert d.route_to == "local"
    assert d.reason == "DOMAIN_REQUIRES_LOCAL"


def test_no_redaction_forces_local():
    d = ModelRoutingGuard().decide(primary_domain="general", sensitivity="public", redaction_applied=False)
    assert d.route_to == "local"
    assert d.reason == "NO_REDACTION_CLOUD_FORBIDDEN"


def test_low_risk_redacted_allows_cloud():
    d = ModelRoutingGuard().decide(primary_domain="general", sensitivity="public", redaction_applied=True)
    assert d.route_to == "cloud"


def test_sensitivity_takes_priority_over_domain():
    """Sensitivity check runs before domain check."""
    d = ModelRoutingGuard().decide(primary_domain="finance", sensitivity="sensitive", redaction_applied=True)
    assert d.reason == "SENSITIVITY_REQUIRES_LOCAL"
