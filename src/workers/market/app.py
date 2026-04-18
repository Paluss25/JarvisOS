"""CFO Market Workers — FastAPI application.

Sub-agents mounted:
  POST /market-data/analyze      — Polymarket active markets + prices (CLOB)
  POST /risk/analyze             — Portfolio exposure and risk level (DB)
  POST /strategy/analyze         — Opportunity identification + LLM ranking
  POST /journal/analyze          — Trade performance history (DB)
  POST /position-sizing/analyze  — Kelly criterion position sizing (pure calc)
"""

from fastapi import FastAPI

from workers.market import journal, market_data, position_sizing, risk, strategy

app = FastAPI(
    title="CFO Market Workers",
    description="Prediction market sub-agents for the CFO agent",
    version="1.0.0",
)

app.include_router(market_data.router, prefix="/market-data")
app.include_router(risk.router, prefix="/risk")
app.include_router(strategy.router, prefix="/strategy")
app.include_router(journal.router, prefix="/journal")
app.include_router(position_sizing.router, prefix="/position-sizing")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "cfo-market-workers"}
