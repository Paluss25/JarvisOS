"""YNAB Categorization sub-agent — category assignment for transactions.

Rules engine for known patterns; haiku LLM for ambiguous cases.
"""

import re

from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import llm

router = APIRouter()

# Rules: (regex pattern on payee/memo) → category
_RULES: list[tuple[re.Pattern, str]] = [
    # Groceries
    (re.compile(r"esselunga|coop|lidl|aldi|penny|eurospin|carrefour|supermercato", re.I), "Groceries"),
    (re.compile(r"amazon|amzn|prime", re.I), "Shopping"),
    (re.compile(r"spotify|netflix|disney\+|apple music|youtube premium", re.I), "Subscriptions"),
    (re.compile(r"eni|agip|esso|bp|total|q8|benzina|carburante|fuel", re.I), "Transportation: Fuel"),
    (re.compile(r"trenitalia|italo|frecciarossa|atm|atac|bus|metro|tram|ztl", re.I), "Transportation: Public"),
    (re.compile(r"farmacia|parafarmacia|pharmacy|medic", re.I), "Health"),
    (re.compile(r"ristorante|restaurant|trattoria|pizzeria|bar |caffè|caffe|food delivery|just eat|glovo|deliveroo|uber eat", re.I), "Dining Out"),
    (re.compile(r"palestra|gym|fitness|sport|decathlon|intersport", re.I), "Health & Fitness"),
    (re.compile(r"enel|eni gas|a2a|hera|luce e gas|elettricità|acqua|telecom|tim |vodafone|wind|fastweb|iliad", re.I), "Utilities"),
    (re.compile(r"affitto|rent|locazione|mutuo|mortgage", re.I), "Housing"),
    (re.compile(r"assicurazione|insurance|rca|polizza", re.I), "Insurance"),
    (re.compile(r"binance|coinbase|kraken|bitpanda|crypto|bitcoin|ethereum", re.I), "Investments: Crypto"),
    (re.compile(r"banca|bank|atm |prelievo|bonifico", re.I), "Banking & Transfers"),
]

_SYSTEM = (
    "You are a financial transaction categorizer for an Italian user. "
    "Given a payee name and optional memo, return exactly ONE category from this list: "
    "Groceries, Shopping, Subscriptions, Transportation: Fuel, Transportation: Public, "
    "Health, Dining Out, Health & Fitness, Utilities, Housing, Insurance, "
    "Investments: Crypto, Banking & Transfers, Entertainment, Travel, Education, Other. "
    "Reply with ONLY the category name, nothing else."
)


class Transaction(BaseModel):
    payee: str
    amount: float
    memo: str = ""


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _rules_match(payee: str, memo: str) -> str | None:
    text = f"{payee} {memo}"
    for pattern, category in _RULES:
        if pattern.search(text):
            return category
    return None


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    transactions = task.scope.get("transactions", [])
    if not transactions:
        return {"error": "scope.transactions is required (list of {payee, amount, memo})"}

    results = []
    llm_calls = 0

    for tx in transactions:
        payee = tx.get("payee", "")
        memo = tx.get("memo", "")
        amount = tx.get("amount", 0)

        # Rules first
        category = _rules_match(payee, memo)
        method = "rules"

        if not category:
            # LLM fallback for ambiguous transactions
            try:
                prompt = f"Payee: {payee}\nMemo: {memo}\nAmount: {amount} EUR"
                category = (await llm.complete(prompt, system=_SYSTEM)).strip()
                method = "llm"
                llm_calls += 1
            except Exception:
                category = "Other"
                method = "fallback"

        results.append({
            "payee": payee,
            "amount": amount,
            "memo": memo,
            "category": category,
            "method": method,
        })

    return {
        "transaction_count": len(results),
        "llm_calls": llm_calls,
        "categorized": results,
    }
