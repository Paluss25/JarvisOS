from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ApprovalDecision:
    allow: bool
    decision: str
    reasons: List[str] = field(default_factory=list)
    required_class: Optional[str] = None


class ApprovalChecker:
    def __init__(self, approval_policy: Dict[str, Any]) -> None:
        self.approval_policy = approval_policy
        approval_classes = approval_policy.get("approval_classes", {})
        self.auto_allowed = set(approval_classes.get("auto_allowed", {}).get("actions", []))
        self.human_required = set(approval_classes.get("human_approval_required", {}).get("actions", []))
        self.two_step_required = set(approval_classes.get("two_step_approval_required", {}).get("actions", []))

    def evaluate(self, *, action_type: str, target_id: Optional[str], token: Optional[Dict[str, Any]]) -> ApprovalDecision:
        if action_type in self.auto_allowed:
            return ApprovalDecision(True, "allow", ["AUTO_ALLOWED"])

        if action_type in self.human_required:
            return self._validate_required_token(action_type=action_type, target_id=target_id, token=token, required_class="human_approval_required")

        if action_type in self.two_step_required:
            return self._validate_required_token(action_type=action_type, target_id=target_id, token=token, required_class="two_step_approval_required")

        return ApprovalDecision(False, "deny", ["UNKNOWN_ACTION_CLASS"])

    def _validate_required_token(self, *, action_type: str, target_id: Optional[str], token: Optional[Dict[str, Any]], required_class: str) -> ApprovalDecision:
        if not token:
            return ApprovalDecision(False, "require_approval", ["APPROVAL_TOKEN_MISSING"], required_class)

        if token.get("approval_class") != required_class:
            return ApprovalDecision(False, "deny", ["TOKEN_APPROVAL_CLASS_MISMATCH"], required_class)

        if token.get("action_type") != action_type:
            return ApprovalDecision(False, "deny", ["TOKEN_ACTION_MISMATCH"], required_class)

        if target_id is not None and token.get("target_id") != target_id:
            return ApprovalDecision(False, "deny", ["TOKEN_TARGET_MISMATCH"], required_class)

        if token.get("used") is True:
            return ApprovalDecision(False, "deny", ["TOKEN_REPLAY_DETECTED"], required_class)

        expires_at = token.get("expires_at")
        if not expires_at:
            return ApprovalDecision(False, "deny", ["TOKEN_MISSING_EXPIRY"], required_class)

        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return ApprovalDecision(False, "deny", ["TOKEN_INVALID_TIMESTAMP"], required_class)

        if expiry < datetime.now(timezone.utc):
            return ApprovalDecision(False, "deny", ["TOKEN_EXPIRED"], required_class)

        if required_class == "two_step_approval_required" and not token.get("secondary_approver_identity"):
            return ApprovalDecision(False, "deny", ["SECONDARY_APPROVER_MISSING"], required_class)

        signature = token.get("signature")
        if not signature or len(str(signature)) < 16:
            return ApprovalDecision(False, "deny", ["TOKEN_SIGNATURE_INVALID"], required_class)

        return ApprovalDecision(True, "allow", ["APPROVAL_TOKEN_VALID"], required_class)
