"""CFO Cost Workers — FastAPI application.

Sub-agents mounted:
  POST /ai-cost/analyze       — LLM/AI infrastructure spend (Prometheus)
  POST /power-cost/analyze    — Electricity consumption and EUR cost
  POST /budget-control/analyze — YNAB budget vs spending status
  POST /forecast/analyze      — Cost trend projection + LLM commentary
  POST /roi/analyze           — Hardware buy vs lease analysis
"""

from fastapi import FastAPI

from workers.cost import ai_cost, budget_control, forecast, power_cost, roi

app = FastAPI(
    title="CFO Cost Workers",
    description="Cost analysis sub-agents for the CFO agent",
    version="1.0.0",
)

app.include_router(ai_cost.router, prefix="/ai-cost")
app.include_router(power_cost.router, prefix="/power-cost")
app.include_router(budget_control.router, prefix="/budget-control")
app.include_router(forecast.router, prefix="/forecast")
app.include_router(roi.router, prefix="/roi")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "cfo-cost-workers"}
