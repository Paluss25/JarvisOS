"""Medical safety gate — detects red flags and screens advice for safety."""

import re
from dataclasses import dataclass
from enum import Enum

class ApprovalStatus(str, Enum):
    APPROVED = "approved"
    APPROVED_WITH_CONSTRAINTS = "approved_with_constraints"
    NOT_APPROVED = "not_approved"

@dataclass
class MedicalScreenResult:
    status: ApprovalStatus
    constraints: list[str]
    escalation_advice: str
    safe_interim_guidance: str

_RED_FLAGS = re.compile(
    r"\b(chest\s*pain|dolore\s*al\s*petto|tachicardi[ae]|"
    r"faint|svenimento|blood\s*in|sangue|shortness\s*of\s*breath|"
    r"affanno|sudden\s*weakness|debolezza\s*improvvisa|"
    r"severe\s*headache|forte\s*mal\s*di\s*testa|"
    r"numbness|intorpidimento|blurred\s*vision|vista\s*offuscata)\b",
    re.IGNORECASE,
)

_CAUTION_FLAGS = re.compile(
    r"\b(injury|infortunio|medication|farmac[oi]|"
    r"pain|dolore|hurt[s]?|hurting|ache[s]?|dizziness|vertigo|nausea|"
    r"pregnant|incinta|chronic|cronico|"
    r"eating\s*disorder|disturbo\s*alimentare|"
    r"rapid\s*weight\s*loss)\b",
    re.IGNORECASE,
)

def screen_input(message: str) -> MedicalScreenResult:
    if _RED_FLAGS.search(message):
        return MedicalScreenResult(
            status=ApprovalStatus.NOT_APPROVED,
            constraints=[],
            escalation_advice="These symptoms may require professional evaluation. Please consult a healthcare provider if they persist or worsen.",
            safe_interim_guidance="In the meantime: rest, avoid intense exercise, stay hydrated. If symptoms are acute, seek medical attention.",
        )
    if _CAUTION_FLAGS.search(message):
        constraints = []
        if re.search(r"\b(injury|infortunio|pain|dolore|hurt[s]?|hurting|ache[s]?)\b", message, re.IGNORECASE):
            constraints.append("Avoid exercises that stress the affected area")
        if re.search(r"\b(medication|farmac[oi])\b", message, re.IGNORECASE):
            constraints.append("Consider medication interactions with nutrition advice")
        if re.search(r"\b(eating\s*disorder|disturbo\s*alimentare)\b", message, re.IGNORECASE):
            constraints.append("Avoid restrictive diet language; focus on nourishment")
        if re.search(r"\b(rapid\s*weight\s*loss)\b", message, re.IGNORECASE):
            constraints.append("Rapid weight loss (>1kg/week sustained) warrants medical review")
        return MedicalScreenResult(
            status=ApprovalStatus.APPROVED_WITH_CONSTRAINTS,
            constraints=constraints,
            escalation_advice="",
            safe_interim_guidance="",
        )
    return MedicalScreenResult(
        status=ApprovalStatus.APPROVED,
        constraints=[],
        escalation_advice="",
        safe_interim_guidance="",
    )
