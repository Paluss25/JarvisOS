"""Tests for PermissionLayer (layer 6)."""

import pytest
from security.pipeline.permission_layer import PermissionLayer, PermissionResult


def test_unknown_agent_denied():
    layer = PermissionLayer(permissions_config={"agents": {}})
    result = layer.check(agent_id="ghost", requested_tools=["send_email"])
    assert result.allowed is False
    assert "UNKNOWN_AGENT" in result.reasons


def test_denied_tool_blocked():
    config = {
        "agents": {
            "email_intelligence_agent": {
                "permissions": {
                    "denied": ["delete_email"],
                    "execute": []
                }
            }
        }
    }
    layer = PermissionLayer(permissions_config=config)
    result = layer.check(agent_id="email_intelligence_agent", requested_tools=["delete_email"])
    assert result.allowed is False
    assert any("TOOL_DENIED" in r for r in result.reasons)


def test_tool_not_in_execute_list_blocked():
    config = {
        "agents": {
            "email_intelligence_agent": {
                "permissions": {
                    "denied": [],
                    "execute": ["read_email", "quarantine_email"]
                }
            }
        }
    }
    layer = PermissionLayer(permissions_config=config)
    result = layer.check(agent_id="email_intelligence_agent", requested_tools=["send_email"])
    assert result.allowed is False
    assert any("TOOL_NOT_ALLOWED" in r for r in result.reasons)


def test_allowed_tools_pass():
    config = {
        "agents": {
            "email_intelligence_agent": {
                "permissions": {
                    "denied": [],
                    "execute": ["read_email", "quarantine_email"]
                }
            }
        }
    }
    layer = PermissionLayer(permissions_config=config)
    result = layer.check(agent_id="email_intelligence_agent", requested_tools=["read_email"])
    assert result.allowed is True
    assert result.denied_tools == []


def test_empty_execute_list_allows_any_tool():
    """When execute list is empty, no whitelist constraint — only denied list applies."""
    config = {
        "agents": {
            "email_intelligence_agent": {
                "permissions": {
                    "denied": [],
                    "execute": []
                }
            }
        }
    }
    layer = PermissionLayer(permissions_config=config)
    result = layer.check(agent_id="email_intelligence_agent", requested_tools=["any_tool"])
    assert result.allowed is True


def test_multiple_tools_mixed_result():
    """One allowed, one denied — overall allowed=False."""
    config = {
        "agents": {
            "email_intelligence_agent": {
                "permissions": {
                    "denied": ["delete_email"],
                    "execute": []
                }
            }
        }
    }
    layer = PermissionLayer(permissions_config=config)
    result = layer.check(agent_id="email_intelligence_agent", requested_tools=["read_email", "delete_email"])
    assert result.allowed is False
    assert "delete_email" in result.denied_tools
    assert "read_email" not in result.denied_tools
