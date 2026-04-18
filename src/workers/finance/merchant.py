"""Merchant Resolution sub-agent — normalize merchant names.

Embedded pattern database (~120 merchants). No external API calls.
"""

import re

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# (pattern, normalized_name, category)
_MERCHANTS: list[tuple[re.Pattern, str, str]] = [
    # Groceries
    (re.compile(r"esselunga", re.I), "Esselunga", "Groceries"),
    (re.compile(r"\bcoop\b", re.I), "Coop", "Groceries"),
    (re.compile(r"lidl", re.I), "Lidl", "Groceries"),
    (re.compile(r"aldi", re.I), "Aldi", "Groceries"),
    (re.compile(r"penny", re.I), "Penny Market", "Groceries"),
    (re.compile(r"eurospin", re.I), "Eurospin", "Groceries"),
    (re.compile(r"carrefour", re.I), "Carrefour", "Groceries"),
    (re.compile(r"iper\b|ipercoop", re.I), "Iper", "Groceries"),
    (re.compile(r"pam\b|panorama", re.I), "PAM", "Groceries"),
    (re.compile(r"il gigante", re.I), "Il Gigante", "Groceries"),
    # Online shopping
    (re.compile(r"amazon|amzn", re.I), "Amazon", "Shopping"),
    (re.compile(r"ebay", re.I), "eBay", "Shopping"),
    (re.compile(r"zalando", re.I), "Zalando", "Shopping"),
    (re.compile(r"shein", re.I), "Shein", "Shopping"),
    (re.compile(r"aliexpress", re.I), "AliExpress", "Shopping"),
    (re.compile(r"mediaworld|media world", re.I), "MediaWorld", "Electronics"),
    (re.compile(r"unieuro", re.I), "Unieuro", "Electronics"),
    # Streaming
    (re.compile(r"netflix", re.I), "Netflix", "Subscriptions"),
    (re.compile(r"spotify", re.I), "Spotify", "Subscriptions"),
    (re.compile(r"disney\+|disneyplus", re.I), "Disney+", "Subscriptions"),
    (re.compile(r"apple\s*(tv|music|one|icloud)", re.I), "Apple", "Subscriptions"),
    (re.compile(r"youtube\s*premium", re.I), "YouTube Premium", "Subscriptions"),
    (re.compile(r"paramount\+", re.I), "Paramount+", "Subscriptions"),
    (re.compile(r"dazn", re.I), "DAZN", "Subscriptions"),
    (re.compile(r"sky\b", re.I), "Sky", "Subscriptions"),
    # Food delivery
    (re.compile(r"just eat|justeat", re.I), "Just Eat", "Dining: Delivery"),
    (re.compile(r"deliveroo", re.I), "Deliveroo", "Dining: Delivery"),
    (re.compile(r"glovo", re.I), "Glovo", "Dining: Delivery"),
    (re.compile(r"uber\s*eat", re.I), "Uber Eats", "Dining: Delivery"),
    # Transport
    (re.compile(r"trenitalia", re.I), "Trenitalia", "Transportation"),
    (re.compile(r"italo\b", re.I), "Italo NTV", "Transportation"),
    (re.compile(r"frecciarossa|freccia", re.I), "Trenitalia Frecce", "Transportation"),
    (re.compile(r"ryanair", re.I), "Ryanair", "Transportation: Air"),
    (re.compile(r"easyjet", re.I), "EasyJet", "Transportation: Air"),
    (re.compile(r"wizz\s*air", re.I), "Wizz Air", "Transportation: Air"),
    (re.compile(r"uber\b(?!\s*eat)", re.I), "Uber", "Transportation: Taxi"),
    (re.compile(r"enjoy\b|share\s*now|free2move", re.I), "Car Sharing", "Transportation"),
    # Fuel
    (re.compile(r"\beni\b|agip", re.I), "Eni/Agip", "Transportation: Fuel"),
    (re.compile(r"\besso\b", re.I), "Esso", "Transportation: Fuel"),
    (re.compile(r"\bbp\b|british petroleum", re.I), "BP", "Transportation: Fuel"),
    (re.compile(r"\bq8\b", re.I), "Q8", "Transportation: Fuel"),
    (re.compile(r"\btotal\b", re.I), "TotalEnergies", "Transportation: Fuel"),
    # Utilities
    (re.compile(r"enel\b", re.I), "Enel", "Utilities: Electricity"),
    (re.compile(r"a2a\b", re.I), "A2A", "Utilities"),
    (re.compile(r"\bhera\b", re.I), "Hera", "Utilities"),
    (re.compile(r"iren\b", re.I), "Iren", "Utilities"),
    (re.compile(r"telecom|tim\b", re.I), "TIM", "Utilities: Telecom"),
    (re.compile(r"vodafone", re.I), "Vodafone", "Utilities: Telecom"),
    (re.compile(r"wind\b|tre\b|\b3\b", re.I), "Wind Tre", "Utilities: Telecom"),
    (re.compile(r"fastweb", re.I), "Fastweb", "Utilities: Telecom"),
    (re.compile(r"iliad", re.I), "Iliad", "Utilities: Telecom"),
    # Pharmacy
    (re.compile(r"farmacia|parafarmacia", re.I), "Farmacia", "Health"),
    (re.compile(r"lloyds\s*farmacia", re.I), "Lloyd's Farmacia", "Health"),
    # Fitness
    (re.compile(r"decathlon", re.I), "Decathlon", "Health & Fitness"),
    (re.compile(r"intersport", re.I), "Intersport", "Health & Fitness"),
    (re.compile(r"virgin\s*active|mcfit|planet\s*fitness|palestra", re.I), "Gym", "Health & Fitness"),
    # Crypto
    (re.compile(r"binance", re.I), "Binance", "Investments: Crypto"),
    (re.compile(r"coinbase", re.I), "Coinbase", "Investments: Crypto"),
    (re.compile(r"kraken", re.I), "Kraken", "Investments: Crypto"),
    (re.compile(r"bitpanda", re.I), "Bitpanda", "Investments: Crypto"),
    (re.compile(r"nexo\b", re.I), "Nexo", "Investments: Crypto"),
    # Restaurants (generic)
    (re.compile(r"mcdonald|mc donald|mcdonalds", re.I), "McDonald's", "Dining: Fast Food"),
    (re.compile(r"burger\s*king", re.I), "Burger King", "Dining: Fast Food"),
    (re.compile(r"kfc\b|kentucky", re.I), "KFC", "Dining: Fast Food"),
    (re.compile(r"old\s*wild\s*west", re.I), "Old Wild West", "Dining"),
    (re.compile(r"autogrillAuto|autogrill", re.I), "Autogrill", "Dining"),
    # Insurance
    (re.compile(r"generali\b", re.I), "Generali", "Insurance"),
    (re.compile(r"allianz", re.I), "Allianz", "Insurance"),
    (re.compile(r"unipol|unipolsai", re.I), "UnipolSai", "Insurance"),
    (re.compile(r"zurich\b", re.I), "Zurich", "Insurance"),
    # Education
    (re.compile(r"udemy", re.I), "Udemy", "Education"),
    (re.compile(r"coursera", re.I), "Coursera", "Education"),
    (re.compile(r"linkedin\s*learning", re.I), "LinkedIn Learning", "Education"),
]


def resolve(merchant_name: str) -> dict:
    for pattern, normalized, category in _MERCHANTS:
        if pattern.search(merchant_name):
            return {
                "input": merchant_name,
                "normalized": normalized,
                "category": category,
                "confidence": 0.95,
                "method": "pattern",
            }
    # No match
    return {
        "input": merchant_name,
        "normalized": merchant_name.title(),
        "category": "Other",
        "confidence": 0.3,
        "method": "passthrough",
    }


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    # Accept a single merchant_name or a list
    merchant_name = task.scope.get("merchant_name")
    merchants = task.scope.get("merchants", [])

    if merchant_name:
        merchants = [merchant_name]

    if not merchants:
        return {"error": "scope.merchant_name or scope.merchants (list) is required"}

    results = [resolve(m) for m in merchants]

    return {
        "count": len(results),
        "resolved": results,
    }
