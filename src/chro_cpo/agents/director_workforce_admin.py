from __future__ import annotations

from typing import Dict

from chro_cpo.agents.base import BaseAgent
from chro_cpo.core.routing import Router
from chro_cpo.core.types import AgentResult, CaseEnvelope


class DirectorWorkforceAdministrationAgent(BaseAgent):
    agent_id = "director_workforce_admin"

    def __init__(self, specialists: Dict[str, BaseAgent]) -> None:
        self.specialists = specialists
        self.router = Router()

    def run(self, case: CaseEnvelope) -> AgentResult:
        text = case.input_text.lower()
        used = []
        specialist_results = []

        if any(x in text for x in ["busta paga", "cedolino", "stipendio", "netto", "lordo", "payroll"]):
            used.append("payroll_intelligence")
        if any(x in text for x in ["ferie", "permessi", "malattia", "trasferta", "rimborso", "travel", "expense"]):
            used.append("leave_time_travel")
        if any(x in text for x in ["pensione", "contributi", "inps", "benefit", "welfare", "retirement"]):
            used.append("pension_benefits")

        if not used:
            used = [self.router.route(case)]
            if used == ["director_workforce_admin"]:
                used = ["payroll_intelligence"]

        for agent_id in used:
            specialist_results.append(self.specialists[agent_id].run(case))

        confidence = min(result.confidence for result in specialist_results)
        payload = {
            "case_classification": {
                "domain": case.domain,
                "risk": case.risk,
                "jurisdiction": case.jurisdiction,
            },
            "delegated_agents_used": used,
            "consolidated_findings": [r.payload for r in specialist_results],
            "unresolved_issues": [
                issue
                for r in specialist_results
                for issue in r.payload.get("open_questions", []) + r.payload.get("risks_and_uncertainties", [])
            ],
            "recommended_next_steps": ["Review specialist outputs and connect production data sources."],
            "human_review_required": case.risk in {"high", "critical"} or confidence < 0.70,
        }
        escalations = []
        if payload["human_review_required"]:
            escalations.append("human_review_required")
        return AgentResult(self.agent_id, confidence, payload, escalations, payload["human_review_required"])
