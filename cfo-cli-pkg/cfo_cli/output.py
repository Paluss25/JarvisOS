import json

import click


def render(obj: object, human: bool) -> None:
    if not human:
        click.echo(json.dumps(obj, indent=2, default=str))
        return

    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        columns = list(obj[0].keys())
        click.echo("| " + " | ".join(columns) + " |")
        click.echo("|" + "|".join(["---"] * len(columns)) + "|")
        for row in obj:
            click.echo("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
        return

    click.echo(json.dumps(obj, indent=2, default=str))
