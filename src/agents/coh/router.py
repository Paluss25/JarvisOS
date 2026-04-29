"""DrHouse request router — classifies user input and determines routing."""

from dataclasses import dataclass, field
import re

@dataclass
class RoutePlan:
    consult: list[str] = field(default_factory=list)  # ["dos", "don"]
    medical_gate_first: bool = False
    reasoning: str = ""
    is_strategic: bool = False  # DrHouse handles directly

# Keywords (Italian + English)
_NUTRITION_KW = re.compile(
    r"\b(meal|food|calori[ae]|macro|protein[ae]?|carb|fat|grasso|"
    r"barcode|pasto|pranzo|cena|colazione|snack|mangia[ato]*|dieta|"
    r"kcal|nutrition|nutrizione|porzione|portion|pizza|pasta|"
    r"burger|salad|insalata|riso|rice|pollo|chicken|pesce|fish|"
    r"verdura|vegetable|frutta|fruit|dessert|dolce|bevanda|drink)\b",
    re.IGNORECASE,
)
_SPORT_KW = re.compile(
    r"\b(workout|run(?:ning|s)?|corsa|training|allenamento|palestra|gym|"
    r"strava|tennis|strength|forza|hiit|cardio|session[ei]?|"
    r"recovery|recupero|deload|exercise|esercizio)\b",
    re.IGNORECASE,
)
_MEDICAL_KW = re.compile(
    r"\b(pain|dolore|dizziness|vertigo|chest|petto|tachicardi[ae]|"
    r"injury|infortunio|nausea|medication|farmac[oi]|blood\s*pressure|"
    r"pressione|faint|svenimento|vomit|headache|mal\s*di\s*testa|"
    r"eating\s*disorder|disturbo\s*alimentare)\b",
    re.IGNORECASE,
)
_STRATEGIC_KW = re.compile(
    r"\b(goal|obiettivo|progress|progresso|trend|andamento|"
    r"week|settimana|report|overview|panoramica|plan|piano|"
    r"summary|riepilogo|strategy|strategia)\b",
    re.IGNORECASE,
)

def classify(message: str, has_image: bool = False, has_barcode: bool = False) -> RoutePlan:
    plan = RoutePlan()
    text = message.lower()
    if has_image or has_barcode:
        plan.consult.append("don")
    if _MEDICAL_KW.search(text):
        plan.medical_gate_first = True
    has_nutrition = bool(_NUTRITION_KW.search(text))
    has_sport = bool(_SPORT_KW.search(text))
    has_strategic = bool(_STRATEGIC_KW.search(text))
    if has_nutrition and "don" not in plan.consult:
        plan.consult.append("don")
    if has_sport:
        plan.consult.append("dos")
    if has_strategic and not plan.consult:
        plan.is_strategic = True
        plan.reasoning = "Strategic health question — DrHouse handles directly"
        return plan
    if not plan.consult:
        plan.is_strategic = True
        plan.reasoning = "General health question — no specific director needed"
        return plan
    directors = ", ".join(plan.consult)
    medical = " (medical gate first)" if plan.medical_gate_first else ""
    plan.reasoning = f"Route to: {directors}{medical}"
    return plan
