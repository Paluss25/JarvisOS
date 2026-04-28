from __future__ import annotations

from chro_cpo.core.orchestrator import Orchestrator
from chro_cpo.core.types import CaseEnvelope


def main() -> None:
    case = CaseEnvelope(
        case_id="demo-001",
        domain="multi_domain",
        intent="summarize",
        risk="medium",
        data_sensitivity="confidential_hr",
        jurisdiction="it-IT",
        actionability="advisory_only",
        input_text="Controlla la mia busta paga e dimmi anche quante ferie residue ho.",
    )
    orchestrator = Orchestrator()
    result = orchestrator.handle(case)
    print(result)


if __name__ == "__main__":
    main()
