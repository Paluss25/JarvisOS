import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(name="kill-switch", help="Emergency kill-switch management")
def group() -> None:
    pass


@group.command("list")
@click.pass_context
def list_switches(ctx: click.Context) -> None:
    """List all kill switches and their status."""
    with client() as api_client:
        response = api_client.get("/kill-switches")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("trigger")
@click.argument("name")
@click.option("--reason", default=None, help="Why this switch is being triggered")
@click.pass_context
def trigger(ctx: click.Context, name: str, reason: str | None) -> None:
    """Activate a kill switch by name (creates it if missing)."""
    body: dict = {}
    if reason:
        body["reason"] = reason
    with client() as api_client:
        response = api_client.post(f"/kill-switches/{name}/trigger", json=body)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("clear")
@click.argument("name")
@click.pass_context
def clear(ctx: click.Context, name: str) -> None:
    """Clear (deactivate) an active kill switch."""
    with client() as api_client:
        response = api_client.post(f"/kill-switches/{name}/clear")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
