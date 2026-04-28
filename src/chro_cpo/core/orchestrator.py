from __future__ import annotations

from typing import Dict

from chro_cpo.core.policies import PolicyChecker
from chro_cpo.core.routing import Router
from chro_cpo.core.types import AgentResult, CaseEnvelope
from chro_cpo.agents.payroll import PayrollIntelligenceAgent
from chro_cpo.agents.leave_time_travel import LeaveTimeTravelAgent
from chro_cpo.agents.pension_benefits import PensionBenefitsAgent
from chro_cpo.agents.director_workforce_admin import DirectorWorkforceAdministrationAgent


class Orchestrator:
    def __init__(self) -> None:
        self.router = Router()
        self.policies = PolicyChecker()
        self.specialists: Dict[str, object] = {
            "payroll_intelligence": PayrollIntelligenceAgent(),
            "leave_time_travel": LeaveTimeTravelAgent(),
            "pension_benefits": PensionBenefitsAgent(),
        }
        self.director = DirectorWorkforceAdministrationAgent(self.specialists)

    def handle(self, case: CaseEnvelope) -> AgentResult:
        policy = self.policies.evaluate_risk(case.risk)
        route = self.router.route(case)
        if route == "director_workforce_admin":
            result = self.director.run(case)
        else:
            result = self.specialists[route].run(case)  # type: ignore[call-arg]

        if policy.human_review_required:
            result.human_review_required = True
            if "human_review_required" not in result.escalations:
                result.escalations.append("human_review_required")
        return result
