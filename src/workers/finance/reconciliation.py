"""Finance Reconciliation sub-agent — match YNAB transactions vs bank statement.

Pure calculation — no external API calls.
Matching strategy: amount + date proximity (±3 days).
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _parse_amount(v) -> float:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return 0.0


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    ynab_txns = task.scope.get("ynab_transactions", [])
    bank_txns = task.scope.get("bank_transactions", [])

    if not ynab_txns or not bank_txns:
        return {"error": "scope.ynab_transactions and scope.bank_transactions are required"}

    from datetime import date as date_type, timedelta

    def parse_date(s: str | None):
        if not s:
            return None
        try:
            return date_type.fromisoformat(s[:10])
        except ValueError:
            return None

    matched = []
    unmatched_ynab = list(ynab_txns)
    unmatched_bank = list(bank_txns)

    for ynab_tx in ynab_txns:
        ynab_amount = _parse_amount(ynab_tx.get("amount"))
        ynab_date = parse_date(ynab_tx.get("date"))
        best_match = None

        for bank_tx in list(unmatched_bank):
            bank_amount = _parse_amount(bank_tx.get("amount"))
            bank_date = parse_date(bank_tx.get("date"))

            amount_match = abs(ynab_amount - bank_amount) < 0.02

            if ynab_date and bank_date:
                date_diff = abs((ynab_date - bank_date).days)
                date_match = date_diff <= 3
            else:
                date_match = True  # no date available, trust amount only

            if amount_match and date_match:
                best_match = bank_tx
                break

        if best_match:
            matched.append({"ynab": ynab_tx, "bank": best_match})
            unmatched_bank.remove(best_match)
            unmatched_ynab = [t for t in unmatched_ynab if t is not ynab_tx]

    return {
        "matched_count": len(matched),
        "unmatched_ynab_count": len(unmatched_ynab),
        "unmatched_bank_count": len(unmatched_bank),
        "match_rate": round(len(matched) / max(len(ynab_txns), 1) * 100, 1),
        "matched": matched,
        "unmatched_ynab": unmatched_ynab,
        "unmatched_bank": unmatched_bank,
    }
