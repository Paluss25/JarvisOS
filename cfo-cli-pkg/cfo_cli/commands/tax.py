import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Tax lot queries and writes")
def group() -> None:
    pass


@group.command()
@click.option("--asset-id", type=int, help="Filter by asset id")
@click.pass_context
def lots(ctx: click.Context, asset_id: int | None) -> None:
    params: dict[str, int] = {}
    if asset_id is not None:
        params["asset_id"] = asset_id

    with client() as api_client:
        response = api_client.get("/ledger/tax-lots", params=params)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command(name="add-lot")
@click.option("--asset-id", required=True, type=int)
@click.option("--acquired-at", required=True, help="ISO datetime")
@click.option("--quantity-open", required=True, type=float)
@click.option("--unit-cost-eur", required=True, type=float)
@click.option("--method", required=True)
@click.option("--financial-event-id", type=int)
@click.option("--account-id", type=int)
@click.option("--source-lot-ref")
@click.pass_context
def add_lot(
    ctx: click.Context,
    asset_id: int,
    acquired_at: str,
    quantity_open: float,
    unit_cost_eur: float,
    method: str,
    financial_event_id: int | None,
    account_id: int | None,
    source_lot_ref: str | None,
) -> None:
    payload = {
        "asset_id": asset_id,
        "acquired_at": acquired_at,
        "quantity_open": quantity_open,
        "unit_cost_eur": unit_cost_eur,
        "method": method,
        "financial_event_id": financial_event_id,
        "account_id": account_id,
        "source_lot_ref": source_lot_ref,
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    with client() as api_client:
        response = api_client.post("/ledger/tax-lots", json=payload)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
