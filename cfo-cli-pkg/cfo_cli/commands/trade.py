import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Paper trading journal")
def group() -> None:
    pass


@group.command(name="paper-open")
@click.argument("symbol")
@click.option("--direction", required=True, type=click.Choice(["BUY", "SELL"], case_sensitive=False), help="BUY or SELL")
@click.option("--entry", required=True, type=float, help="Entry price in EUR")
@click.option("--qty", required=True, type=float, help="Quantity")
@click.option("--thesis", default=None, help="Trade thesis / rationale")
@click.option("--stop", default=None, type=float, help="Stop loss price in EUR")
@click.option("--tp", default=None, type=float, help="Take profit price in EUR")
@click.pass_context
def paper_open(
    ctx: click.Context,
    symbol: str,
    direction: str,
    entry: float,
    qty: float,
    thesis: str | None,
    stop: float | None,
    tp: float | None,
) -> None:
    """Open a paper trade position."""
    payload = {
        "symbol": symbol.upper(),
        "direction": direction.upper(),
        "entry_price_eur": entry,
        "quantity": qty,
    }
    if thesis:
        payload["thesis"] = thesis
    if stop is not None:
        payload["stop_loss_eur"] = stop
    if tp is not None:
        payload["take_profit_eur"] = tp

    with client() as api_client:
        response = api_client.post("/trade/paper-open", json=payload)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command(name="paper-close")
@click.argument("trade_id", type=int)
@click.option("--exit-price", required=True, type=float, help="Exit price in EUR")
@click.option("--notes", default=None, help="Outcome notes")
@click.pass_context
def paper_close(
    ctx: click.Context,
    trade_id: int,
    exit_price: float,
    notes: str | None,
) -> None:
    """Close an open paper trade by ID."""
    payload: dict = {"exit_price_eur": exit_price}
    if notes:
        payload["notes"] = notes

    with client() as api_client:
        response = api_client.post(f"/trade/paper-close/{trade_id}", json=payload)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command(name="track-record")
@click.pass_context
def track_record(ctx: click.Context) -> None:
    """Show all paper trades with realized / unrealized P&L."""
    with client() as api_client:
        response = api_client.get("/trade/track-record")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
