"""CFO Cost Workers — FastAPI application.

Sub-agents mounted:
  POST /ai-cost/analyze       — LLM/AI infrastructure spend (Prometheus)
  POST /power-cost/analyze    — Electricity consumption and EUR cost
  POST /budget-control/analyze — YNAB budget vs spending status
  POST /forecast/analyze      — Legacy cost trend projection + LLM commentary
  POST /subscription-tracker/analyze — Recurring merchant detection
  POST /cashflow-forecast/analyze    — 3/6/12 month cashflow forecast
  POST /tax-withholding/analyze      — YTD IRPEF estimate
  POST /roi/analyze           — Hardware buy vs lease analysis
"""

from fastapi import FastAPI

from workers.cost import ai_cost, budget_control, cashflow_forecast
from workers.cost import forecast, power_cost, roi, subscription_tracker, tax_withholding

app = FastAPI(
    title="CFO Cost Workers",
    description="Cost analysis sub-agents for the CFO agent",
    version="1.0.0",
)

app.include_router(ai_cost.router, prefix="/ai-cost")
app.include_router(power_cost.router, prefix="/power-cost")
app.include_router(budget_control.router, prefix="/budget-control")
app.include_router(forecast.router, prefix="/forecast")
app.include_router(subscription_tracker.router, prefix="/subscription-tracker")
app.include_router(cashflow_forecast.router, prefix="/cashflow-forecast")
app.include_router(tax_withholding.router, prefix="/tax-withholding")
app.include_router(roi.router, prefix="/roi")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "cfo-cost-workers"}
