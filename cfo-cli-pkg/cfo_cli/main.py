import click

from cfo_cli.commands import approval
from cfo_cli.commands import bitpanda
from cfo_cli.commands import config as config_cmd
from cfo_cli.commands import kill_switch
from cfo_cli.commands import ledger
from cfo_cli.commands import market
from cfo_cli.commands import mortgage
from cfo_cli.commands import portfolio
from cfo_cli.commands import signal
from cfo_cli.commands import strategy
from cfo_cli.commands import tax
from cfo_cli.commands import trade


@click.group()
@click.option("--human", is_flag=True, help="Render tables instead of JSON")
@click.pass_context
def cli(ctx: click.Context, human: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["human"] = human


cli.add_command(portfolio.group, name="portfolio")
cli.add_command(bitpanda.group, name="bitpanda")
cli.add_command(ledger.group, name="ledger")
cli.add_command(market.group, name="market")
cli.add_command(mortgage.group, name="mortgage")
cli.add_command(tax.group, name="tax")
cli.add_command(strategy.group, name="strategy")
cli.add_command(trade.group, name="trade")
cli.add_command(signal.group, name="signal")
cli.add_command(approval.group, name="approval")
cli.add_command(kill_switch.group, name="kill-switch")
cli.add_command(config_cmd.group, name="config")


if __name__ == "__main__":
    cli()
