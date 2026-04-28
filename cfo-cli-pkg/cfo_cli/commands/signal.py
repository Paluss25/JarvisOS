import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Signal queue management")
def group() -> None:
    pass


@group.command("create")
@click.argument("signal_type")
@click.option("--severity", default="info", show_default=True)
@click.option("--asset-id", type=int, default=None)
@click.option("--payload", default=None, help="JSON string payload")
@click.pass_context
def create(ctx: click.Context, signal_type: str, severity: str, asset_id: int | None, payload: str | None) -> None:
    """Emit a new signal into the queue."""
    import json
    body: dict = {"signal_type": signal_type, "severity": severity}
    if asset_id is not None:
        body["asset_id"] = asset_id
    if payload:
        body["payload"] = json.loads(payload)
    with client() as api_client:
        response = api_client.post("/signals", json=body)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("list")
@click.option("--status", default=None, help="Filter by status (e.g. active)")
@click.pass_context
def list_signals(ctx: click.Context, status: str | None) -> None:
    """List signals, optionally filtered by status."""
    params = {}
    if status:
        params["status"] = status
    with client() as api_client:
        response = api_client.get("/signals", params=params)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("ack")
@click.argument("signal_id", type=int)
@click.pass_context
def ack(ctx: click.Context, signal_id: int) -> None:
    """Acknowledge (resolve) a signal."""
    with client() as api_client:
        response = api_client.post(f"/signals/{signal_id}/ack")
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
