from __future__ import annotations

from chro_cpo.agents.base import BaseAgent
from chro_cpo.core.types import AgentResult, CaseEnvelope


class LeaveTimeTravelAgent(BaseAgent):
    agent_id = "leave_time_travel"

    def run(self, case: CaseEnvelope) -> AgentResult:
        payload = {
            "rule_source": "unconfigured",
            "extracted_records": {"note": "Implement leave/time/travel extraction here."},
            "computed_balances": {},
            "anomalies": [],
            "confidence": 0.65,
            "next_steps": ["Connect leave policy source and calculator."],
            "plain_language_summary": "Leave/time/travel case recognized. The implementation scaffold is ready, but the data connectors and calculator must still be implemented.",
        }
        return AgentResult(self.agent_id, payload["confidence"], payload)
