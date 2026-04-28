import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Portfolio queries")
def group() -> None:
    pass


@group.command()
@click.pass_context
def snapshot(ctx: click.Context) -> None:
    with client() as api_client:
        response = api_client.get("/portfolio/snapshot")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command(name="net-worth")
@click.pass_context
def net_worth(ctx: click.Context) -> None:
    with client() as api_client:
        response = api_client.get("/portfolio/net-worth")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.option("--class", "asset_class", help="Filter by asset class")
@click.pass_context
def positions(ctx: click.Context, asset_class: str | None) -> None:
    path = "/portfolio/positions"
    if asset_class:
        path = f"{path}?asset_class={asset_class}"
    with client() as api_client:
        response = api_client.get(path)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.pass_context
def cashflow(ctx: click.Context) -> None:
    with client() as api_client:
        response = api_client.get("/portfolio/cashflow")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.option("--source", help="Filter by source")
@click.option("--class", "asset_class", help="Filter by asset class")
@click.pass_context
def holdings(ctx: click.Context, source: str | None, asset_class: str | None) -> None:
    params: dict[str, str] = {}
    if source:
        params["source"] = source
    if asset_class:
        params["asset_class"] = asset_class
    with client() as api_client:
        response = api_client.get("/portfolio/holdings", params=params)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command(name="add-manual-holding")
@click.option("--account-ref", required=True)
@click.option("--account-name", required=True)
@click.option("--account-type", required=True)
@click.option("--symbol", required=True)
@click.option("--name", "asset_name", required=True)
@click.option("--class", "asset_class", required=True)
@click.option("--quantity", required=True, type=float)
@click.option("--avg-cost-eur", type=float)
@click.option("--value-eur", "market_value_eur", required=True, type=float)
@click.option("--captured-at", required=True)
@click.pass_context
def add_manual_holding(
    ctx: click.Context,
    account_ref: str,
    account_name: str,
    account_type: str,
    symbol: str,
    asset_name: str,
    asset_class: str,
    quantity: float,
    avg_cost_eur: float | None,
    market_value_eur: float,
    captured_at: str,
) -> None:
    payload = {
        "account_reference": account_ref,
        "account_name": account_name,
        "account_type": account_type,
        "symbol": symbol,
        "asset_name": asset_name,
        "asset_class": asset_class,
        "quantity": quantity,
        "avg_cost_eur": avg_cost_eur,
        "market_value_eur": market_value_eur,
        "captured_at": captured_at,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    with client() as api_client:
        response = api_client.post("/portfolio/holdings/manual", json=payload)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
