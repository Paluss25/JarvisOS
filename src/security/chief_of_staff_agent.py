from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional

from security.policy_engine import AgentRequest, PolicyDecision, PolicyEngine


@dataclass
class RoutingDecision:
    decision_id: str
    email_id: str
    thread_id: Optional[str]
    decision_type: str
    final_targets: List[Dict[str, str]]
    actions: List[str]
    archive_policy: Dict[str, Any]
    escalation: Dict[str, Any]
    executive_summary: str
    confidence: float
    priority: Optional[str] = None
    policy_flags: Optional[Dict[str, Any]] = None


class BaseChiefOfStaffReasoner:
    def decide(self, payload: Dict[str, Any]) -> RoutingDecision:
        raise NotImplementedError


class DeterministicChiefOfStaffReasoner(BaseChiefOfStaffReasoner):
    """Fast deterministic router used as default and fallback.

    This intentionally handles the common cases with explicit rules so the
    system stays predictable and testable. Ambiguous cases are marked for
    internal review or escalation rather than over-reaching.
    """

    def decide(self, payload: Dict[str, Any]) -> RoutingDecision:
        email_id = payload.get("email_id", "unknown_email")
        thread_id = payload.get("thread_id")
        classification = payload.get("classification", {})
        entities = payload.get("entities", {})
        security = payload.get("security_signals", {})

        primary = classification.get("primary_domain", "general")
        secondary = list(classification.get("secondary_domains", []) or [])
        priority = classification.get("priority")
        confidence = float(classification.get("confidence", 0.5))
        sensitivity = classification.get("sensitivity")
        amount = _max_amount(entities)

        if security.get("prompt_injection_risk") in {"high", "critical"}:
            return RoutingDecision(
                decision_id=f"cos_{email_id}",
                email_id=email_id,
                thread_id=thread_id,
                decision_type="multi_route",
                final_targets=[
                    {"agent": "CISOAgent", "reason": "Prompt-injection or manipulation risk detected"},
                    {"agent": "ChiefOfStaffAgent", "reason": "Manual coordination required"},
                ],
                actions=["store_email", "request_domain_analysis", "request_human_review"],
                archive_policy=_archive_policy(primary, secondary, sensitivity),
                escalation={"needed": False, "target": None, "reason": None},
                executive_summary="High-risk email with instruction-like content from an untrusted source.",
                confidence=max(confidence, 0.9),
                priority=priority,
                policy_flags={
                    "requires_approval_before_execution": True,
                    "cloud_processing_forbidden": True,
                    "quarantine_recommended": True,
                },
            )

        if security.get("suspicious_domain") and primary in {"finance", "security"}:
            return RoutingDecision(
                decision_id=f"cos_{email_id}",
                email_id=email_id,
                thread_id=thread_id,
                decision_type="multi_route",
                final_targets=[
                    {"agent": "CISOAgent", "reason": "Suspicious sender/domain"},
                    {"agent": "CFOAgent", "reason": "Potential financial fraud vector"},
                ],
                actions=["store_email", "request_domain_analysis", "priority_notify"],
                archive_policy=_archive_policy(primary, secondary, sensitivity),
                escalation={"needed": False, "target": None, "reason": None},
                executive_summary="Suspicious sender attempting a finance-related action.",
                confidence=max(confidence, 0.88),
                priority=priority,
                policy_flags={
                    "requires_approval_before_execution": True,
                    "cloud_processing_forbidden": True,
                    "quarantine_recommended": True,
                },
            )

        if primary == "finance" and "legal" in secondary:
            escalation_needed = bool(amount is not None and amount >= 10000)
            return RoutingDecision(
                decision_id=f"cos_{email_id}",
                email_id=email_id,
                thread_id=thread_id,
                decision_type="multi_route_and_escalate" if escalation_needed else "multi_route",
                final_targets=[
                    {"agent": "CFOAgent", "reason": "Financial review required"},
                    {"agent": "CLOAgent", "reason": "Legal review required"},
                ],
                actions=["store_email", "store_attachments", "request_domain_analysis"],
                archive_policy=_archive_policy(primary, secondary, sensitivity),
                escalation={
                    "needed": escalation_needed,
                    "target": "CEOAgent" if escalation_needed else None,
                    "reason": "Material finance/legal impact" if escalation_needed else None,
                },
                executive_summary="Email affects both finance and legal domains.",
                confidence=max(confidence, 0.84),
                priority=priority,
                policy_flags={
                    "requires_approval_before_execution": True,
                    "cloud_processing_forbidden": sensitivity in {"sensitive", "critical"},
                    "quarantine_recommended": False,
                },
            )

        if primary == "legal" and "finance" in secondary:
            escalation_needed = bool(amount is not None and amount >= 10000)
            return RoutingDecision(
                decision_id=f"cos_{email_id}",
                email_id=email_id,
                thread_id=thread_id,
                decision_type="multi_route_and_escalate" if escalation_needed else "multi_route",
                final_targets=[
                    {"agent": "CLOAgent", "reason": "Legal review required"},
                    {"agent": "CFOAgent", "reason": "Financial impact assessment required"},
                ],
                actions=["store_email", "store_attachments", "request_domain_analysis"],
                archive_policy=_archive_policy(primary, secondary, sensitivity),
                escalation={
                    "needed": escalation_needed,
                    "target": "CEOAgent" if escalation_needed else None,
                    "reason": "Material legal/financial impact" if escalation_needed else None,
                },
                executive_summary="Contract or legal notice with financial implications.",
                confidence=max(confidence, 0.84),
                priority=priority,
                policy_flags={
                    "requires_approval_before_execution": True,
                    "cloud_processing_forbidden": sensitivity in {"sensitive", "critical"},
                    "quarantine_recommended": False,
                },
            )

        if confidence < 0.80:
            return RoutingDecision(
                decision_id=f"cos_{email_id}",
                email_id=email_id,
                thread_id=thread_id,
                decision_type="internal_review",
                final_targets=[
                    {"agent": "ChiefOfStaffAgent", "reason": "Ambiguous classification or low confidence"},
                ],
                actions=["hold_routing", "request_reasoning_pass"],
                archive_policy=_archive_policy(primary, secondary, sensitivity),
                escalation={"needed": False, "target": None, "reason": None},
                executive_summary="Routing confidence is below threshold; keeping under CoS review.",
                confidence=confidence,
                priority=priority,
                policy_flags={
                    "requires_approval_before_execution": False,
                    "cloud_processing_forbidden": sensitivity in {"sensitive", "critical"},
                    "quarantine_recommended": False,
                },
            )

        target_map = {
            "finance": "CFOAgent",
            "security": "CISOAgent",
            "infrastructure": "CIOAgent",
            "legal": "CLOAgent",
            "operations": "COOAgent",
            "general": "ChiefOfStaffAgent",
        }
        target = target_map.get(primary, "ChiefOfStaffAgent")
        reason = {
            "CFOAgent": "Finance domain ownership",
            "CISOAgent": "Security domain ownership",
            "CIOAgent": "Infrastructure domain ownership",
            "CLOAgent": "Legal domain ownership",
            "COOAgent": "Operations follow-up",
            "ChiefOfStaffAgent": "General triage or coordination",
        }[target]

        decision_type = "ignore" if primary == "general" and priority == "low" else "route_and_review"
        actions = ["store_email"] if decision_type == "ignore" else ["store_email", "request_domain_analysis"]
        if target == "COOAgent":
            actions.append("request_execution_plan")

        return RoutingDecision(
            decision_id=f"cos_{email_id}",
            email_id=email_id,
            thread_id=thread_id,
            decision_type=decision_type,
            final_targets=[] if decision_type == "ignore" else [{"agent": target, "reason": reason}],
            actions=actions,
            archive_policy=_archive_policy(primary, secondary, sensitivity),
            escalation={"needed": False, "target": None, "reason": None},
            executive_summary=f"Routed to {target} based on primary domain '{primary}'.",
            confidence=max(confidence, 0.8),
            priority=priority,
            policy_flags={
                "requires_approval_before_execution": False,
                "cloud_processing_forbidden": sensitivity in {"sensitive", "critical"},
                "quarantine_recommended": False,
            },
        )


class LLMReasonerAdapter(BaseChiefOfStaffReasoner):
    """Thin adapter around an injected callable.

    The callable receives the structured email payload and must return either a
    `RoutingDecision` or a plain dict compatible with it. This keeps the repo
    model-agnostic and easy to plug into LiteLLM/OpenClaw later.
    """

    def __init__(self, infer: Callable[[Dict[str, Any]], Any]) -> None:
        self._infer = infer

    def decide(self, payload: Dict[str, Any]) -> RoutingDecision:
        result = self._infer(payload)
        if isinstance(result, RoutingDecision):
            return result
        if isinstance(result, dict):
            return RoutingDecision(**result)
        raise TypeError("LLM reasoner must return RoutingDecision or dict")


class HybridChiefOfStaffAgent:
    """Hybrid CoS implementation.

    Flow:
    1. Evaluate safety/policy constraints for the routing operation.
    2. Run deterministic routing for common cases.
    3. Optionally invoke an LLM adapter only for ambiguous/complex cases.
    4. Re-validate the resulting decision against policy-derived constraints.
    """

    def __init__(self, policy_engine: PolicyEngine, llm_reasoner: Optional[BaseChiefOfStaffReasoner] = None) -> None:
        self.policy_engine = policy_engine
        self.fallback_reasoner = DeterministicChiefOfStaffReasoner()
        self.llm_reasoner = llm_reasoner

    def route(
        self,
        payload: Dict[str, Any],
        runtime_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        runtime_state = runtime_state or {}
        policy = self.policy_engine.evaluate(
            payload=payload,
            request=AgentRequest(
                agent_id="ChiefOfStaffAgent",
                requested_action="route_and_review",
                requested_model_class=runtime_state.get("requested_model_class", "local"),
            ),
            runtime_state=runtime_state,
        )

        if not policy.allow and policy.decision in {"deny", "require_approval"}:
            return self._policy_blocking_decision(payload, policy)

        deterministic = self.fallback_reasoner.decide(payload)
        final_decision = deterministic

        if self._should_use_llm(payload, deterministic, policy) and self.llm_reasoner is not None:
            llm_candidate = self.llm_reasoner.decide(payload)
            final_decision = self._merge_decisions(deterministic, llm_candidate)

        final_decision = self._apply_policy_constraints(final_decision, policy)
        return asdict(final_decision)

    def _should_use_llm(
        self,
        payload: Dict[str, Any],
        deterministic: RoutingDecision,
        policy: PolicyDecision,
    ) -> bool:
        classification = payload.get("classification", {})
        secondary = classification.get("secondary_domains", []) or []
        confidence = float(classification.get("confidence", 0.5))
        amount = _max_amount(payload.get("entities", {}))

        if policy.constraints.get("route_to") == "cloud_allowed":
            return True
        if deterministic.decision_type == "internal_review":
            return True
        if len(secondary) >= 2:
            return True
        if amount is not None and amount >= 5000:
            return True
        return confidence < 0.9

    def _merge_decisions(self, deterministic: RoutingDecision, llm_candidate: RoutingDecision) -> RoutingDecision:
        """Conservative merge: prefer deterministic safety shape, allow the LLM
        to refine targets/summary/actions when it doesn't reduce safety.
        """
        merged = RoutingDecision(**asdict(deterministic))

        if llm_candidate.final_targets:
            merged.final_targets = llm_candidate.final_targets
        if llm_candidate.actions:
            merged.actions = sorted(set(deterministic.actions + llm_candidate.actions))
        if llm_candidate.executive_summary:
            merged.executive_summary = llm_candidate.executive_summary
        if llm_candidate.priority is not None:
            merged.priority = llm_candidate.priority
        merged.confidence = max(deterministic.confidence, llm_candidate.confidence)

        # Never downgrade an escalation requirement.
        if llm_candidate.escalation.get("needed"):
            merged.escalation = llm_candidate.escalation
            merged.decision_type = llm_candidate.decision_type

        # Keep the most restrictive policy flags.
        merged.policy_flags = {
            **(deterministic.policy_flags or {}),
            **(llm_candidate.policy_flags or {}),
            "requires_approval_before_execution": (
                (deterministic.policy_flags or {}).get("requires_approval_before_execution", False)
                or (llm_candidate.policy_flags or {}).get("requires_approval_before_execution", False)
            ),
            "cloud_processing_forbidden": (
                (deterministic.policy_flags or {}).get("cloud_processing_forbidden", False)
                or (llm_candidate.policy_flags or {}).get("cloud_processing_forbidden", False)
            ),
            "quarantine_recommended": (
                (deterministic.policy_flags or {}).get("quarantine_recommended", False)
                or (llm_candidate.policy_flags or {}).get("quarantine_recommended", False)
            ),
        }
        return merged

    def _apply_policy_constraints(self, decision: RoutingDecision, policy: PolicyDecision) -> RoutingDecision:
        route_constraint = policy.constraints.get("route_to")
        if route_constraint == "local_only":
            flags = decision.policy_flags or {}
            flags["cloud_processing_forbidden"] = True
            decision.policy_flags = flags
        if policy.decision == "escalate":
            flags = decision.policy_flags or {}
            flags["quarantine_recommended"] = bool(policy.constraints.get("quarantine"))
            decision.policy_flags = flags
            route_to = policy.constraints.get("route_to")
            if route_to and not any(t["agent"] == route_to for t in decision.final_targets):
                decision.final_targets.insert(0, {"agent": route_to, "reason": "Policy-enforced security routing"})
        return decision

    def _policy_blocking_decision(self, payload: Dict[str, Any], policy: PolicyDecision) -> Dict[str, Any]:
        email_id = payload.get("email_id", "unknown_email")
        return asdict(
            RoutingDecision(
                decision_id=f"cos_{email_id}",
                email_id=email_id,
                thread_id=payload.get("thread_id"),
                decision_type="internal_review",
                final_targets=[{"agent": "ChiefOfStaffAgent", "reason": "Policy blocked automatic routing"}],
                actions=["hold_routing", "request_human_review"],
                archive_policy=_archive_policy(
                    payload.get("classification", {}).get("primary_domain", "general"),
                    payload.get("classification", {}).get("secondary_domains", []),
                    payload.get("classification", {}).get("sensitivity"),
                ),
                escalation={"needed": False, "target": None, "reason": None},
                executive_summary=f"Routing paused because policy returned '{policy.decision}'.",
                confidence=1.0,
                priority=payload.get("classification", {}).get("priority"),
                policy_flags={
                    "requires_approval_before_execution": policy.decision == "require_approval",
                    "cloud_processing_forbidden": True,
                    "quarantine_recommended": False,
                },
            )
        )


def _max_amount(entities: Dict[str, Any]) -> Optional[float]:
    amounts = entities.get("amounts", []) or []
    values: List[float] = []
    for item in amounts:
        try:
            values.append(float(item.get("value")))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _archive_policy(primary: str, secondary: List[str], sensitivity: Optional[str]) -> Dict[str, Any]:
    domains = [primary] + [d for d in secondary if d]
    retention_tag = "_".join(sorted(set(domains))) if domains else "general"
    return {
        "store_raw": True,
        "store_structured": True,
        "store_embeddings": sensitivity not in {"critical"},
        "retention_tag": retention_tag,
    }
