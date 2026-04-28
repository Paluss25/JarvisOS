import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Bitpanda raw sync and queries")
def group() -> None:
    pass


@group.command()
@click.pass_context
def sync(ctx: click.Context) -> None:
    with client() as api_client:
        response = api_client.post("/bitpanda/raw/sync")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.option("--limit", type=int, default=100, show_default=True)
@click.pass_context
def balances(ctx: click.Context, limit: int) -> None:
    with client() as api_client:
        response = api_client.get("/bitpanda/balances", params={"limit": limit})
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.option("--limit", type=int, default=100, show_default=True)
@click.pass_context
def transactions(ctx: click.Context, limit: int) -> None:
    with client() as api_client:
        response = api_client.get("/bitpanda/transactions", params={"limit": limit})
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.pass_context
def summary(ctx: click.Context) -> None:
    with client() as api_client:
        response = api_client.get("/bitpanda/summary")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
