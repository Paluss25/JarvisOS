"""Email Transaction Extraction sub-agent — extract transactions from email text.

Regex patterns for Italian bank notification emails + haiku LLM for unstructured text.
"""

import re

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import llm

router = APIRouter()

# Italian bank email patterns
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "Pagamento di 45,90 EUR a Amazon"
    (re.compile(r"(?:pagamento|addebito|prelievo)\s+(?:di\s+)?([\d,.]+)\s*(EUR|€)\s+(?:a|da|presso)\s+(.+?)(?:\.|$)", re.I), "outflow"),
    # "Accredito di 1.500,00 EUR da Stipendio"
    (re.compile(r"accredito\s+(?:di\s+)?([\d,.]+)\s*(EUR|€)\s+da\s+(.+?)(?:\.|$)", re.I), "inflow"),
    # "Hai speso 23.50€ da COOP"
    (re.compile(r"(?:hai speso|spesa di)\s*([\d,.]+)\s*(?:EUR|€)\s+(?:da|presso|a)\s+(.+?)(?:\.|$)", re.I), "outflow"),
    # Generic: "€ 99,99 - Netflix"
    (re.compile(r"(?:EUR|€)\s*([\d,.]+)\s*[-–]\s*(.+?)(?:\.|$)", re.I), "unknown"),
]

_SYSTEM = (
    "You are a financial data extractor. Given an email text, extract all financial transactions. "
    "For each transaction return a JSON object with: "
    "payee (string), amount (float, always positive), direction ('inflow' or 'outflow'), "
    "currency (string, default 'EUR'), date (YYYY-MM-DD if found, else null). "
    "Return a JSON array of transaction objects. If no transactions found, return []. "
    "Return ONLY the JSON array, no explanation."
)


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _parse_amount(s: str) -> float:
    """Parse Italian-format number (1.234,56) to float."""
    cleaned = s.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    email_text = task.scope.get("email_text", "")
    if not email_text:
        return {"error": "scope.email_text is required"}

    # Try regex patterns first
    transactions = []
    for pattern, direction in _PATTERNS:
        for match in pattern.finditer(email_text):
            groups = match.groups()
            if len(groups) >= 2:
                amount_str = groups[0]
                payee = groups[-1].strip()
                transactions.append({
                    "payee": payee,
                    "amount": _parse_amount(amount_str),
                    "direction": direction,
                    "currency": "EUR",
                    "date": None,
                    "method": "regex",
                })

    # If regex found nothing, use LLM
    if not transactions:
        try:
            import json
            response = await llm.complete(email_text, system=_SYSTEM)
            # Strip markdown code fences if present
            response = re.sub(r"```(?:json)?\s*", "", response).strip().rstrip("`")
            parsed = json.loads(response)
            if isinstance(parsed, list):
                for tx in parsed:
                    tx["method"] = "llm"
                transactions = parsed
        except Exception as exc:
            return {"transactions": [], "error": f"LLM extraction failed: {exc}"}

    return {
        "transaction_count": len(transactions),
        "transactions": transactions,
    }
