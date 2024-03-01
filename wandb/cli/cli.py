#!/usr/bin/env python
import logging
import sys

import click

import wandb
import wandb.env
from wandb.cli.commands import (
    agent,
    artifact,
    beta,
    controller,
    disabled,
    docker,
    docker_run,
    enabled,
    gc,
    importer,
    init,
    job,
    launch,
    launch_agent,
    launch_sweep,
    local,
    login,
    magic,
    off,
    offline,
    on,
    online,
    projects,
    pull,
    restore,
    scheduler,
    server,
    service,
    status,
    sweep,
    sync,
    verify,
)
from wandb.cli.utils.errors import display_error
from wandb.cli.utils.logger import get_wandb_cli_log_path

# TODO: remove this once we fix the test
_wandb_log_path = get_wandb_cli_log_path()

logging.basicConfig(
    filename=_wandb_log_path,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger("wandb")


class RunGroup(click.Group):
    @display_error
    def get_command(self, ctx, cmd_name):
        # TODO: check if cmd_name is a file in the current dir and not require `run`?
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv
        return None


@click.command(cls=RunGroup, invoke_without_command=True)
@click.version_option(version=wandb.__version__)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# add all the subcommands to the cli
cli.add_command(agent)
cli.add_command(artifact)
cli.add_command(beta)
cli.add_command(controller)
cli.add_command(disabled)
cli.add_command(docker)
cli.add_command(docker_run)
cli.add_command(enabled)
cli.add_command(gc)
cli.add_command(importer)
cli.add_command(init)
cli.add_command(job)
cli.add_command(launch)
cli.add_command(launch_agent)
cli.add_command(launch_sweep)
cli.add_command(local)
cli.add_command(login)
cli.add_command(magic)
cli.add_command(off)
cli.add_command(offline)
cli.add_command(on)
cli.add_command(online)
cli.add_command(projects)
cli.add_command(pull)
cli.add_command(restore)
cli.add_command(scheduler)
cli.add_command(server)
cli.add_command(service)
cli.add_command(status)
cli.add_command(sweep)
cli.add_command(sync)
cli.add_command(verify)
