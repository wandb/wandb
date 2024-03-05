import configparser
import os

import click

import wandb
from wandb.apis import InternalApi
from wandb.cli.utils.errors import display_error


@click.command("online", help="Enable W&B sync")
@display_error
def online():
    api = InternalApi()
    try:
        api.clear_setting("disabled", persist=True)
        api.clear_setting("mode", persist=True)
    except configparser.Error:
        pass
    click.echo(
        "W&B online. Running your script from this directory will now sync to the cloud."
    )


@click.command(
    "on",
    hidden=True,
)
@click.pass_context
@display_error
def on(ctx):
    ctx.invoke(online)


@click.command(
    "enabled",
    help="Enable W&B.",
)
@click.option(
    "--service",
    is_flag=True,
    show_default=True,
    default=True,
    help="Enable W&B service",
)
def enabled(service):
    api = InternalApi()
    try:
        api.set_setting("mode", "online", persist=True)
        click.echo("W&B enabled.")
        os.environ[wandb.env._DISABLE_SERVICE] = str(not service)
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn on W&B:\nexport WANDB_MODE=online"
        )
