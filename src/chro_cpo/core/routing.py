from __future__ import annotations

from chro_cpo.core.types import CaseEnvelope


class Router:
    def route(self, case: CaseEnvelope) -> str:
        text = case.input_text.lower()
        payroll_hits = any(x in text for x in ["busta paga", "cedolino", "stipendio", "netto", "lordo", "payroll"])
        leave_hits = any(x in text for x in ["ferie", "permessi", "malattia", "trasferta", "rimborso", "travel", "expense"])
        pension_hits = any(x in text for x in ["pensione", "contributi", "inps", "benefit", "welfare", "retirement"])

        domains = sum([payroll_hits, leave_hits, pension_hits])
        if domains > 1 or case.domain == "multi_domain":
            return "director_workforce_admin"
        if payroll_hits or case.domain == "payroll":
            return "payroll_intelligence"
        if leave_hits or case.domain == "leave_time_travel":
            return "leave_time_travel"
        if pension_hits or case.domain == "pension_benefits":
            return "pension_benefits"
        return "director_workforce_admin"
