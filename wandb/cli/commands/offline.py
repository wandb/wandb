import configparser
import os

import click

import wandb
from wandb.apis import InternalApi
from wandb.cli.utils.errors import display_error


@click.command(
    "offline",
    help="Disable W&B sync",
)
@display_error
def offline():
    api = InternalApi()
    try:
        api.set_setting("disabled", "true", persist=True)
        api.set_setting("mode", "offline", persist=True)
        click.echo(
            "W&B offline. Running your script from this directory will only write metadata locally. Use wandb disabled to completely turn off W&B."
        )
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=offline"
        )


@click.command(
    "off",
    hidden=True,
)
@click.pass_context
@display_error
def off(ctx):
    ctx.invoke(offline)


@click.command(
    "disabled",
    help="Disable W&B.",
)
@click.option(
    "--service",
    is_flag=True,
    show_default=True,
    default=True,
    help="Disable W&B service",
)
def disabled(service):
    api = InternalApi()
    try:
        api.set_setting("mode", "disabled", persist=True)
        click.echo("W&B disabled.")
        os.environ[wandb.env._DISABLE_SERVICE] = str(service)
    except configparser.Error:
        click.echo(
            "Unable to write config, copy and paste the following in your terminal to turn off W&B:\nexport WANDB_MODE=disabled"
        )
