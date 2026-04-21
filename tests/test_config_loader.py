"""Unit tests for security config_loader."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from security.config_loader import (
    load_all,
    load_permissions,
    load_approval_policy,
    load_memory_policy,
    load_model_routing_rules,
)


# ---------------------------------------------------------------------------
# load_all()
# ---------------------------------------------------------------------------

def test_load_all_returns_all_keys():
    """load_all() must return exactly the four expected top-level keys."""
    cfg = load_all()
    assert set(cfg.keys()) == {"permissions", "approval_policy", "memory_policy", "model_routing_rules"}


def test_load_all_returns_dict():
    """load_all() must return a dict, not None or some other type."""
    cfg = load_all()
    assert isinstance(cfg, dict)


# ---------------------------------------------------------------------------
# load_permissions()
# ---------------------------------------------------------------------------

def test_permissions_has_agents():
    """permissions.yaml must include an 'agents' section."""
    cfg = load_permissions()
    assert "agents" in cfg, "Expected 'agents' key in permissions config"


def test_permissions_is_dict():
    """load_permissions() must return a dict."""
    cfg = load_permissions()
    assert isinstance(cfg, dict)


def test_permissions_agents_is_dict():
    """The 'agents' section must itself be a dict of agent configs."""
    cfg = load_permissions()
    assert isinstance(cfg["agents"], dict), "agents must be a dict"


# ---------------------------------------------------------------------------
# load_approval_policy()
# ---------------------------------------------------------------------------

def test_approval_policy_has_classes():
    """approval-policy.yaml must include an 'approval_classes' section."""
    cfg = load_approval_policy()
    assert "approval_classes" in cfg, "Expected 'approval_classes' key in approval policy"


def test_approval_policy_classes_is_dict():
    """approval_classes must be a dict."""
    cfg = load_approval_policy()
    assert isinstance(cfg["approval_classes"], dict)


def test_approval_policy_has_auto_allowed():
    """approval_classes must define an 'auto_allowed' class."""
    cfg = load_approval_policy()
    assert "auto_allowed" in cfg["approval_classes"], (
        "Expected 'auto_allowed' inside approval_classes"
    )


# ---------------------------------------------------------------------------
# load_memory_policy()
# ---------------------------------------------------------------------------

def test_memory_policy_has_stores():
    """memory-policy.yaml must include a 'stores' section."""
    cfg = load_memory_policy()
    assert "stores" in cfg, "Expected 'stores' key in memory policy"


def test_memory_policy_stores_is_dict():
    """stores must be a dict."""
    cfg = load_memory_policy()
    assert isinstance(cfg["stores"], dict)


def test_memory_policy_is_dict():
    """load_memory_policy() must return a dict."""
    cfg = load_memory_policy()
    assert isinstance(cfg, dict)


# ---------------------------------------------------------------------------
# load_model_routing_rules()
# ---------------------------------------------------------------------------

def test_model_routing_rules_is_dict():
    """load_model_routing_rules() must return a dict."""
    cfg = load_model_routing_rules()
    assert isinstance(cfg, dict)


def test_model_routing_rules_has_model_classes():
    """model-routing-rules.yaml must include a 'model_classes' section."""
    cfg = load_model_routing_rules()
    assert "model_classes" in cfg, "Expected 'model_classes' key in model routing rules"


def test_model_routing_rules_has_routing_rules():
    """model-routing-rules.yaml must include a 'routing_rules' section."""
    cfg = load_model_routing_rules()
    assert "routing_rules" in cfg, "Expected 'routing_rules' key in model routing rules"


# ---------------------------------------------------------------------------
# Consistency: load_all() matches individual loaders
# ---------------------------------------------------------------------------

def test_load_all_permissions_matches_individual():
    """load_all()['permissions'] must equal load_permissions()."""
    assert load_all()["permissions"] == load_permissions()


def test_load_all_approval_policy_matches_individual():
    """load_all()['approval_policy'] must equal load_approval_policy()."""
    assert load_all()["approval_policy"] == load_approval_policy()


def test_load_all_memory_policy_matches_individual():
    """load_all()['memory_policy'] must equal load_memory_policy()."""
    assert load_all()["memory_policy"] == load_memory_policy()


def test_load_all_model_routing_rules_matches_individual():
    """load_all()['model_routing_rules'] must equal load_model_routing_rules()."""
    assert load_all()["model_routing_rules"] == load_model_routing_rules()
