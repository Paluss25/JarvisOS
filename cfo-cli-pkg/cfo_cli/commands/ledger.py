import json

import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Ledger queries and writes")
def group() -> None:
    pass


@group.command()
@click.option("--source", help="Filter by source")
@click.option("--account-id", type=int, help="Filter by account id")
@click.option("--from-date", help="ISO datetime lower bound")
@click.option("--to-date", help="ISO datetime upper bound")
@click.option("--limit", type=int, default=50, show_default=True, help="Max events to return")
@click.pass_context
def events(
    ctx: click.Context,
    source: str | None,
    account_id: int | None,
    from_date: str | None,
    to_date: str | None,
    limit: int,
) -> None:
    params: dict[str, str | int] = {}
    if source:
        params["source"] = source
    if account_id is not None:
        params["account_id"] = account_id
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    params["limit"] = limit

    with client() as api_client:
        response = api_client.get("/ledger/events", params=params)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command(name="add-event")
@click.option("--source", required=True)
@click.option("--type", "event_type", required=True)
@click.option("--external-id", required=True)
@click.option("--amount", required=True, type=float)
@click.option("--currency", required=True)
@click.option("--happened-at", required=True, help="ISO datetime")
@click.option("--account-id", type=int)
@click.option("--asset-id", type=int)
@click.option("--fiat-value-eur", type=float)
@click.option("--fee-eur", type=float)
@click.option("--tx-hash")
@click.option("--counterparty-type")
@click.option("--category")
@click.option("--tax-treatment-candidate")
@click.option("--confidence-score", type=float)
@click.option("--evidence-link")
@click.option("--raw-payload", help="JSON object string")
@click.pass_context
def add_event(
    ctx: click.Context,
    source: str,
    event_type: str,
    external_id: str,
    amount: float,
    currency: str,
    happened_at: str,
    account_id: int | None,
    asset_id: int | None,
    fiat_value_eur: float | None,
    fee_eur: float | None,
    tx_hash: str | None,
    counterparty_type: str | None,
    category: str | None,
    tax_treatment_candidate: str | None,
    confidence_score: float | None,
    evidence_link: str | None,
    raw_payload: str | None,
) -> None:
    payload = {
        "source": source,
        "event_type": event_type,
        "external_id": external_id,
        "amount": amount,
        "currency": currency,
        "happened_at": happened_at,
        "account_id": account_id,
        "asset_id": asset_id,
        "fiat_value_eur": fiat_value_eur,
        "fee_eur": fee_eur,
        "tx_hash": tx_hash,
        "counterparty_type": counterparty_type,
        "category": category,
        "tax_treatment_candidate": tax_treatment_candidate,
        "confidence_score": confidence_score,
        "evidence_link": evidence_link,
        "raw_payload": json.loads(raw_payload) if raw_payload else None,
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    with client() as api_client:
        response = api_client.post("/ledger/events", json=payload)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command(name="add-asset")
@click.option("--symbol", required=True)
@click.option("--name", required=True)
@click.option("--class", "asset_class", required=True)
@click.option("--chain")
@click.option("--isin")
@click.option("--ticker-exchange")
@click.option("--base-currency", default="EUR", show_default=True)
@click.pass_context
def add_asset(
    ctx: click.Context,
    symbol: str,
    name: str,
    asset_class: str,
    chain: str | None,
    isin: str | None,
    ticker_exchange: str | None,
    base_currency: str,
) -> None:
    payload = {
        "symbol": symbol,
        "name": name,
        "asset_class": asset_class,
        "chain": chain,
        "isin": isin,
        "ticker_exchange": ticker_exchange,
        "base_currency": base_currency,
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    with client() as api_client:
        response = api_client.post("/ledger/assets", json=payload)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
