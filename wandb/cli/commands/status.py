import json

import click

from wandb.cli.utils.api import _get_cling_api


@click.command(
    "status",
    help="Show configuration settings",
)
@click.option(
    "--settings/--no-settings", help="Show the current settings", default=True
)
def status(settings):
    api = _get_cling_api()
    if settings:
        click.echo(click.style("Current Settings", bold=True))
        settings = api.settings()
        click.echo(
            json.dumps(settings, sort_keys=True, indent=2, separators=(",", ": "))
        )
