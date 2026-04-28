import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Strategy analytics and risk metrics")
def group() -> None:
    pass


@group.command()
@click.option("--window", type=int, default=90, show_default=True, help="Look-back window in trading days")
@click.pass_context
def risk(ctx: click.Context, window: int) -> None:
    """Portfolio risk metrics: VaR(95%), CVaR, annualized Sharpe per asset."""
    with client() as api_client:
        response = api_client.get("/analytics/risk", params={"window": window})
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.argument("symbol")
@click.option(
    "--indicators",
    default="rsi,macd,sma,bb,atr",
    show_default=True,
    help="Comma-separated indicators: rsi, macd, sma, bb, atr",
)
@click.option("--limit", type=int, default=250, show_default=True, help="Max price history points")
@click.pass_context
def ta(ctx: click.Context, symbol: str, indicators: str, limit: int) -> None:
    """Technical analysis for a symbol (RSI, MACD, SMA, Bollinger Bands, ATR)."""
    with client() as api_client:
        response = api_client.get(
            f"/analytics/ta/{symbol.upper()}",
            params={"indicators": indicators, "limit": limit},
        )
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.option("--lookback", type=int, default=365, show_default=True, help="Price history window in days")
@click.pass_context
def optimize(ctx: click.Context, lookback: int) -> None:
    """Portfolio optimization: max-Sharpe and min-volatility weights with delta vs current allocation."""
    with client() as api_client:
        response = api_client.get("/analytics/optimize", params={"lookback_days": lookback})
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.pass_context
def bonds(ctx: click.Context) -> None:
    """Bond portfolio: YTM, maturity alerts, price dislocations."""
    with client() as api_client:
        response = api_client.get("/analytics/bonds")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
