from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class CaseEnvelope:
    case_id: str
    domain: str
    intent: str
    risk: str
    data_sensitivity: str
    jurisdiction: str
    actionability: str
    input_text: str
    attachments: List[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentResult:
    agent_id: str
    confidence: float
    payload: Dict[str, Any]
    escalations: List[str] = field(default_factory=list)
    human_review_required: bool = False
