"""CFO Finance Workers — FastAPI application.

Sub-agents mounted:
  POST /ynab/analyze            — YNAB monthly spend analysis
  POST /btc-fiscal/analyze      — BTC balance + fiscal report
  POST /fiscal-730/analyze      — Italian Modello 730 / Quadro W
  POST /categorization/analyze  — Transaction category assignment
  POST /email-extraction/analyze — Extract transactions from email text
  POST /reconciliation/analyze  — YNAB vs bank statement match
  POST /merchant/analyze        — Merchant name normalization
"""

from fastapi import FastAPI

from workers.finance import (
    btc_fiscal,
    categorization,
    email_extraction,
    fiscal_730,
    merchant,
    reconciliation,
    ynab,
)

app = FastAPI(
    title="CFO Finance Workers",
    description="Finance sub-agents for the CFO agent",
    version="1.0.0",
)

app.include_router(ynab.router, prefix="/ynab")
app.include_router(btc_fiscal.router, prefix="/btc-fiscal")
app.include_router(fiscal_730.router, prefix="/fiscal-730")
app.include_router(categorization.router, prefix="/categorization")
app.include_router(email_extraction.router, prefix="/email-extraction")
app.include_router(reconciliation.router, prefix="/reconciliation")
app.include_router(merchant.router, prefix="/merchant")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "cfo-finance-workers"}
