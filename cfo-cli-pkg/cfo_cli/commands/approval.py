import click

from cfo_cli.api import client
from cfo_cli.output import render


@click.group(help="Human-in-the-loop approval requests")
def group() -> None:
    pass


@group.command("create")
@click.argument("request_type")
@click.option("--requested-by", required=True, help="Agent or user originating the request")
@click.option("--summary", required=True, help="Human-readable summary")
@click.option("--payload", default=None, help="JSON string payload")
@click.pass_context
def create(ctx: click.Context, request_type: str, requested_by: str, summary: str, payload: str | None) -> None:
    """Create a new approval request."""
    import json
    body: dict = {"request_type": request_type, "requested_by": requested_by, "summary": summary}
    if payload:
        body["payload"] = json.loads(payload)
    with client() as api_client:
        response = api_client.post("/approvals", json=body)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("list")
@click.option("--pending", is_flag=True, help="Show only pending requests")
@click.pass_context
def list_approvals(ctx: click.Context, pending: bool) -> None:
    """List approval requests."""
    params = {}
    if pending:
        params["pending"] = "true"
    with client() as api_client:
        response = api_client.get("/approvals", params=params)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))


@group.command("decide")
@click.argument("approval_id", type=int)
@click.argument("decision", type=click.Choice(["approved", "rejected"]))
@click.option("--decided-by", required=True, help="Who is making the decision")
@click.option("--notes", default=None)
@click.pass_context
def decide(ctx: click.Context, approval_id: int, decision: str, decided_by: str, notes: str | None) -> None:
    """Approve or reject a pending request."""
    body: dict = {"decision": decision, "decided_by": decided_by}
    if notes:
        body["notes"] = notes
    with client() as api_client:
        response = api_client.post(f"/approvals/{approval_id}/decide", json=body)
    response.raise_for_status()
    render(response.json(), human=ctx.obj.get("human", False))
