"""Load security policy YAML files from src/security/config/."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import yaml

_CONFIG_DIR = Path(__file__).parent / "config"


def _load(filename: str) -> Dict[str, Any]:
    return yaml.safe_load((_CONFIG_DIR / filename).read_text(encoding="utf-8"))


def load_permissions() -> Dict[str, Any]:
    return _load("permissions.yaml")


def load_approval_policy() -> Dict[str, Any]:
    return _load("approval-policy.yaml")


def load_memory_policy() -> Dict[str, Any]:
    return _load("memory-policy.yaml")


def load_model_routing_rules() -> Dict[str, Any]:
    return _load("model-routing-rules.yaml")


def load_all() -> Dict[str, Any]:
    return {
        "permissions": load_permissions(),
        "approval_policy": load_approval_policy(),
        "memory_policy": load_memory_policy(),
        "model_routing_rules": load_model_routing_rules(),
    }
