from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryDecision:
    allow: bool
    decision: str
    reasons: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)


class MemoryGuard:
    def __init__(self, memory_policy: Dict[str, Any]) -> None:
        self.memory_policy = memory_policy
        self.stores = memory_policy.get("stores", {})
        self.write_rules = memory_policy.get("write_rules", [])

    def check_write(
        self,
        *,
        agent_id: str,
        target_store: str,
        content_type: str,
        sensitivity: Optional[str],
        redaction_applied: bool,
        retention_tag: Optional[str] = None,
        pii_minimized: Optional[bool] = None,
        namespace: Optional[str] = None,
    ) -> MemoryDecision:
        store_cfg = self.stores.get(target_store)
        if not store_cfg:
            return MemoryDecision(False, "deny", ["UNKNOWN_TARGET_STORE"])

        access_roles = set(store_cfg.get("access_roles", []))
        if agent_id not in access_roles:
            return MemoryDecision(False, "deny", ["AGENT_NOT_AUTHORIZED_FOR_STORE"])

        allowed_content = set(store_cfg.get("allowed_content", []))
        forbidden_content = set(store_cfg.get("forbidden_content", []))

        if content_type in forbidden_content:
            return MemoryDecision(False, "deny", ["CONTENT_TYPE_FORBIDDEN_FOR_STORE"])

        if allowed_content and content_type not in allowed_content:
            return MemoryDecision(False, "deny", ["CONTENT_TYPE_NOT_ALLOWED_FOR_STORE"])

        if target_store == "vector_store" and content_type in {"raw_email_body", "raw_attachment_text"}:
            return MemoryDecision(False, "deny", ["RAW_EMAIL_EMBEDDING_FORBIDDEN"])

        if target_store == "vector_store" and sensitivity in {"sensitive", "critical"} and not redaction_applied:
            return MemoryDecision(False, "deny", ["UNREDACTED_SENSITIVE_VECTOR_WRITE_FORBIDDEN"])

        if target_store == "raw_email_store" and not retention_tag:
            return MemoryDecision(False, "deny", ["RETENTION_TAG_REQUIRED_FOR_RAW_STORE"])

        if target_store == "structured_store":
            requires_min = bool(store_cfg.get("pii_minimized", False))
            if requires_min and pii_minimized is not True:
                return MemoryDecision(False, "deny", ["PII_MINIMIZATION_REQUIRED_FOR_STRUCTURED_STORE"])

        if target_store == "vector_store":
            ns_required = self.stores.get("vector_store", {}).get("namespace_per_domain", False)
            if ns_required and not namespace:
                return MemoryDecision(False, "deny", ["VECTOR_NAMESPACE_REQUIRED"])

        constraints = {}
        if target_store == "vector_store":
            constraints["redaction_required"] = True
            constraints["namespace"] = namespace

        return MemoryDecision(True, "allow", ["MEMORY_WRITE_ALLOWED"], constraints)
