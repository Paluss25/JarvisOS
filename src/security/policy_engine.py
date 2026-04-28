from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class PolicyDecision:
    allow: bool
    decision: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)


@dataclass
class AgentRequest:
    agent_id: str
    requested_action: str
    target_resource: Optional[str] = None
    requested_model_class: Optional[str] = None
    approval_token: Optional[Dict[str, Any]] = None


class PolicyEngine:
    def __init__(
        self,
        permissions: Dict[str, Any],
        approval_policy: Dict[str, Any],
        model_routing_rules: Dict[str, Any],
        memory_policy: Dict[str, Any],
    ) -> None:
        self.permissions = permissions
        self.approval_policy = approval_policy
        self.model_routing_rules = model_routing_rules
        self.memory_policy = memory_policy

    def evaluate(
        self,
        payload: Dict[str, Any],
        request: AgentRequest,
        runtime_state: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        runtime_state = runtime_state or {}

        deny = self._check_hard_denies(payload, request, runtime_state)
        if deny:
            return deny

        quarantine = self._check_quarantine(payload, request, runtime_state)
        if quarantine:
            return quarantine

        model_route = self._check_model_routing(payload, request, runtime_state)
        if model_route and model_route.decision in {"deny", "reroute"}:
            return model_route

        permission = self._check_permissions(request)
        if permission:
            return permission

        approval = self._check_approval(request)
        if approval:
            return approval

        return PolicyDecision(
            allow=True,
            decision="allow",
            constraints=model_route.constraints if model_route else {},
            reasons=(model_route.reasons if model_route else []),
        )

    def check_memory_write(
        self,
        agent_id: str,
        target_store: str,
        content_type: str,
        sensitivity: Optional[str],
        redaction_applied: bool,
    ) -> PolicyDecision:
        if target_store == "vector_store" and content_type in {
            "raw_email_body",
            "raw_attachment_text",
        }:
            return PolicyDecision(
                allow=False,
                decision="deny",
                reasons=["RAW_EMAIL_EMBEDDING_FORBIDDEN"],
            )

        if (
            target_store == "vector_store"
            and sensitivity in {"sensitive", "critical"}
            and not redaction_applied
        ):
            return PolicyDecision(
                allow=False,
                decision="deny",
                reasons=["UNREDACTED_SENSITIVE_VECTOR_WRITE_FORBIDDEN"],
            )

        return PolicyDecision(
            allow=True,
            decision="allow",
            reasons=["MEMORY_WRITE_ALLOWED"],
        )

    def _check_hard_denies(
        self,
        payload: Dict[str, Any],
        request: AgentRequest,
        runtime_state: Dict[str, Any],
    ) -> Optional[PolicyDecision]:
        security = payload.get("security_signals", {})
        classification = payload.get("classification", {})

        if runtime_state.get("active_content_detected") and not runtime_state.get("sanitized", False):
            return PolicyDecision(False, "deny", reasons=["ACTIVE_CONTENT_NOT_SANITIZED"])

        if (
            request.requested_model_class == "cloud"
            and classification.get("sensitivity") in {"sensitive", "critical"}
        ):
            return PolicyDecision(False, "deny", reasons=["CLOUD_NOT_ALLOWED_FOR_SENSITIVE_CONTENT"])

        if request.requested_model_class == "cloud" and not runtime_state.get("redaction_applied", False):
            return PolicyDecision(False, "deny", reasons=["CLOUD_REQUIRES_REDACTION"])

        if request.requested_action == "payment_execution" and not request.approval_token:
            return PolicyDecision(False, "require_approval", reasons=["APPROVAL_TOKEN_MISSING"])

        if security.get("attachment_risk") == "critical" and not runtime_state.get("quarantined", False):
            return PolicyDecision(False, "deny", reasons=["CRITICAL_ATTACHMENT_NOT_QUARANTINED"])

        return None

    def _check_quarantine(
        self,
        payload: Dict[str, Any],
        request: AgentRequest,
        runtime_state: Dict[str, Any],
    ) -> Optional[PolicyDecision]:
        security = payload.get("security_signals", {})

        if security.get("prompt_injection_risk") in {"high", "critical"}:
            return PolicyDecision(
                allow=False,
                decision="escalate",
                constraints={"quarantine": True, "route_to": "cio"},
                reasons=["PROMPT_INJECTION_RISK_HIGH"],
            )

        if security.get("suspicious_domain") and request.requested_action in {
            "route_and_review", "payment_execution", "approve_noncritical_financial_action",
        }:
            return PolicyDecision(
                allow=False,
                decision="escalate",
                constraints={"quarantine": True, "route_to": "cio"},
                reasons=["SUSPICIOUS_DOMAIN_WITH_ACTION_REQUEST"],
            )

        return None

    def _check_model_routing(
        self,
        payload: Dict[str, Any],
        request: AgentRequest,
        runtime_state: Dict[str, Any],
    ) -> Optional[PolicyDecision]:
        classification = payload.get("classification", {})
        primary_domain = classification.get("primary_domain")
        sensitivity = classification.get("sensitivity")

        contains_personal_data = runtime_state.get("contains_personal_data", False)
        contains_payment_data = runtime_state.get("contains_payment_data", False)
        contains_credentials = runtime_state.get("contains_credentials", False)
        redaction_applied = runtime_state.get("redaction_applied", False)
        external_processing_approved = runtime_state.get("external_processing_approved", False)
        provider_approved = runtime_state.get("provider_approved", False)

        if sensitivity in {"sensitive", "critical"}:
            return PolicyDecision(True, "reroute", constraints={"route_to": "local_only"}, reasons=["SENSITIVITY_REQUIRES_LOCAL"])

        if primary_domain in {"finance", "legal", "security"}:
            return PolicyDecision(True, "reroute", constraints={"route_to": "local_only"}, reasons=["DOMAIN_REQUIRES_LOCAL"])

        if contains_personal_data or contains_payment_data or contains_credentials:
            return PolicyDecision(True, "reroute", constraints={"route_to": "local_only"}, reasons=["DATA_CLASS_REQUIRES_LOCAL"])

        if request.requested_model_class == "cloud":
            if not redaction_applied:
                return PolicyDecision(False, "deny", reasons=["CLOUD_REQUIRES_REDACTION"])

            if not external_processing_approved or not provider_approved:
                return PolicyDecision(False, "deny", reasons=["CLOUD_PROVIDER_OR_APPROVAL_MISSING"])

            return PolicyDecision(True, "allow_with_constraints", constraints={"route_to": "cloud_allowed"}, reasons=["CLOUD_ALLOWED_FOR_REDACTED_LOW_RISK_CONTENT"])

        return None

    def _check_permissions(self, request: AgentRequest) -> Optional[PolicyDecision]:
        agent_cfg = self.permissions.get("agents", {}).get(request.agent_id)
        if not agent_cfg:
            return PolicyDecision(False, "deny", reasons=["UNKNOWN_AGENT"])

        denied = set(agent_cfg.get("permissions", {}).get("denied", []))
        allowed_exec = set(agent_cfg.get("permissions", {}).get("execute", []))

        if request.requested_action in denied:
            return PolicyDecision(False, "deny", reasons=["ACTION_OUTSIDE_PERMISSION_SCOPE"])

        if allowed_exec and request.requested_action not in allowed_exec:
            meta_actions = {"reasoning", "route_and_review", "store_only"}
            if request.requested_action not in meta_actions:
                return PolicyDecision(False, "deny", reasons=["ACTION_NOT_EXPLICITLY_ALLOWED"])

        return None

    def _check_approval(self, request: AgentRequest) -> Optional[PolicyDecision]:
        auto_allowed = set(self.approval_policy.get("approval_classes", {}).get("auto_allowed", {}).get("actions", []))
        human_required = set(self.approval_policy.get("approval_classes", {}).get("human_approval_required", {}).get("actions", []))
        two_step_required = set(self.approval_policy.get("approval_classes", {}).get("two_step_approval_required", {}).get("actions", []))

        if request.requested_action in auto_allowed:
            return None

        if request.requested_action in human_required | two_step_required:
            token = request.approval_token
            if not token:
                return PolicyDecision(False, "require_approval", reasons=["APPROVAL_TOKEN_MISSING"])

            token_check = self._validate_token(token, request)
            if token_check is not None:
                return token_check

        return None

    def _validate_token(self, token: Dict[str, Any], request: AgentRequest) -> Optional[PolicyDecision]:
        if token.get("used") is True:
            return PolicyDecision(False, "deny", reasons=["TOKEN_REPLAY_DETECTED"])

        expires_at = token.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if expiry < datetime.now(timezone.utc):
                    return PolicyDecision(False, "deny", reasons=["TOKEN_EXPIRED"])
            except ValueError:
                return PolicyDecision(False, "deny", reasons=["TOKEN_INVALID_TIMESTAMP"])

        if token.get("action_type") != request.requested_action:
            return PolicyDecision(False, "deny", reasons=["TOKEN_ACTION_MISMATCH"])

        if request.target_resource and token.get("target_id") != request.target_resource:
            return PolicyDecision(False, "deny", reasons=["TOKEN_TARGET_MISMATCH"])

        return None
