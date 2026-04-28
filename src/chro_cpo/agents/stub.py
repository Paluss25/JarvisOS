from __future__ import annotations

from chro_cpo.agents.base import BaseAgent
from chro_cpo.core.types import AgentResult, CaseEnvelope


class StubAgent(BaseAgent):
    agent_id = "stub"

    def run(self, case: CaseEnvelope) -> AgentResult:
        return AgentResult(self.agent_id, 0.1, {"note": "stub agent"}, ["not_implemented"], True)
