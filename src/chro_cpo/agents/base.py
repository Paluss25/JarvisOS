from __future__ import annotations

from abc import ABC, abstractmethod

from chro_cpo.core.types import AgentResult, CaseEnvelope


class BaseAgent(ABC):
    agent_id: str

    @abstractmethod
    def run(self, case: CaseEnvelope) -> AgentResult:
        raise NotImplementedError
