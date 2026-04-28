"""CFO Strategy Workers — FastAPI application.

Heavy on-demand sub-agents for Warren (CFO). Each sub-agent is a router
mounted at its own prefix; the path itself encodes the subagent_id.

Sub-agents (skeleton stubs filled by P4.T2 – P4.T6):
  POST /investment-research/analyze   — Asset thesis (Perplexity + Claude synth)
  POST /macro-scenario/analyze        — What-if macro scenario simulation
  POST /correlation-engine/analyze    — Rolling 90-day cross-asset correlation
  POST /rebalancing-advisor/analyze   — Allocation deltas + paper-trade plan
  POST /opportunity-scanner/analyze   — Daily ranked top-N opportunities
"""

from fastapi import FastAPI

from workers.strategy import (
    correlation,
    investment_research,
    macro_scenario,
    opportunity,
    rebalancing,
)

app = FastAPI(
    title="CFO Strategy Workers",
    description="Heavy on-demand strategy sub-agents for the CFO agent",
    version="1.0.0",
)

app.include_router(investment_research.router, prefix="/investment-research")
app.include_router(macro_scenario.router, prefix="/macro-scenario")
app.include_router(correlation.router, prefix="/correlation-engine")
app.include_router(rebalancing.router, prefix="/rebalancing-advisor")
app.include_router(opportunity.router, prefix="/opportunity-scanner")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "cfo-strategy-workers"}
