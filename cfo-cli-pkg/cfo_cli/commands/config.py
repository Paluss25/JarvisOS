import click

from cfo_cli.config import load_config
from cfo_cli.output import render


@click.group(help="CLI configuration")
def group() -> None:
    pass


@group.command("show")
@click.pass_context
def show(ctx: click.Context) -> None:
    render(load_config().model_dump(), human=ctx.obj.get("human", False))
