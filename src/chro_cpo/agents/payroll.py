from __future__ import annotations

from chro_cpo.agents.base import BaseAgent
from chro_cpo.core.types import AgentResult, CaseEnvelope


class PayrollIntelligenceAgent(BaseAgent):
    agent_id = "payroll_intelligence"

    def run(self, case: CaseEnvelope) -> AgentResult:
        payload = {
            "extracted_fields": {"note": "Implement payroll document extraction here."},
            "anomalies": [],
            "comparisons": [],
            "confidence": 0.65,
            "open_questions": ["No payroll parser wired yet."],
            "plain_language_summary": "Payroll case recognized. The implementation scaffold is ready, but document parsing must still be connected.",
        }
        return AgentResult(self.agent_id, payload["confidence"], payload)
