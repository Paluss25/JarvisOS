import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Market prices and quotes")
def group() -> None:
    pass


@group.command()
@click.argument("symbol")
@click.pass_context
def quote(ctx: click.Context, symbol: str) -> None:
    with client() as api_client:
        response = api_client.get(f"/prices/live/{symbol.upper()}")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.option("--limit", type=int, default=100, show_default=True)
@click.pass_context
def macro(ctx: click.Context, limit: int) -> None:
    with client() as api_client:
        response = api_client.get("/macro/indicators", params={"limit": limit})
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command()
@click.option("--limit", type=int, default=50, show_default=True)
@click.pass_context
def news(ctx: click.Context, limit: int) -> None:
    with client() as api_client:
        response = api_client.get("/news/articles", params={"limit": limit})
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("rss-sync")
@click.pass_context
def rss_sync(ctx: click.Context) -> None:
    with client() as api_client:
        response = api_client.post("/news/sync/rss")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("enrich-sentiment")
@click.option("--limit", type=int, default=10, show_default=True)
@click.pass_context
def enrich_sentiment(ctx: click.Context, limit: int) -> None:
    with client() as api_client:
        response = api_client.post("/news/sentiment/enrich", params={"limit": limit})
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
