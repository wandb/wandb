import getpass
import os
import subprocess
import time

import click
from dockerpycreds.utils import find_executable

import wandb
from wandb.apis import InternalApi
from wandb.cli.commands.login import login
from wandb.cli.utils.errors import ClickException, display_error


@click.command(
    name="local",
    context_settings={
        "default_map": {},
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Start a local W&B container (deprecated, see wandb server --help)",
    hidden=True,
)
@click.pass_context
@click.option("--port", "-p", default="8080", help="The host port to bind W&B local on")
@click.option(
    "--env", "-e", default=[], multiple=True, help="Env vars to pass to wandb/local"
)
@click.option(
    "--daemon/--no-daemon", default=True, help="Run or don't run in daemon mode"
)
@click.option(
    "--upgrade", is_flag=True, default=False, help="Upgrade to the most recent version"
)
@click.option(
    "--edge", is_flag=True, default=False, help="Run the bleeding edge", hidden=True
)
@display_error
def local(ctx, *args, **kwargs):
    wandb.termwarn("`wandb local` has been replaced with `wandb server start`.")
    ctx.invoke(start, *args, **kwargs)


@click.group(name="server", help="Commands for operating a local W&B server")
def server():
    pass


@server.command(
    context_settings={
        "default_map": {},
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Start a local W&B server",
)
@click.pass_context
@click.option(
    "--port", "-p", default="8080", help="The host port to bind W&B server on"
)
@click.option(
    "--env", "-e", default=[], multiple=True, help="Env vars to pass to wandb/local"
)
@click.option(
    "--daemon/--no-daemon", default=True, help="Run or don't run in daemon mode"
)
@click.option(
    "--upgrade",
    is_flag=True,
    default=False,
    help="Upgrade to the most recent version",
    hidden=True,
)
@click.option(
    "--edge", is_flag=True, default=False, help="Run the bleeding edge", hidden=True
)
@display_error
def start(ctx, port, env, daemon, upgrade, edge):
    api = InternalApi()
    if not find_executable("docker"):
        raise ClickException("Docker not installed, install it from https://docker.com")
    local_image_sha = wandb.docker.image_id("wandb/local").split("wandb/local")[-1]
    registry_image_sha = wandb.docker.image_id_from_registry("wandb/local").split(
        "wandb/local"
    )[-1]
    if local_image_sha != registry_image_sha:
        if upgrade:
            subprocess.call(["docker", "pull", "wandb/local"])
        else:
            wandb.termlog(
                "A new version of the W&B server is available, upgrade by calling `wandb server start --upgrade`"
            )
    running = subprocess.check_output(
        ["docker", "ps", "--filter", "name=wandb-local", "--format", "{{.ID}}"]
    )
    if running != b"":
        if upgrade:
            subprocess.call(["docker", "stop", "wandb-local"])
        else:
            wandb.termerror(
                "A container named wandb-local is already running, run `docker stop wandb-local` if you want to start a new instance"
            )
            exit(1)
    image = "docker.pkg.github.com/wandb/core/local" if edge else "wandb/local"
    username = getpass.getuser()
    env_vars = ["-e", "LOCAL_USERNAME=%s" % username]
    for e in env:
        env_vars.append("-e")
        env_vars.append(e)
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        "wandb:/vol",
        "-p",
        port + ":8080",
        "--name",
        "wandb-local",
    ] + env_vars
    host = f"http://localhost:{port}"
    api.set_setting("base_url", host, globally=True, persist=True)
    if daemon:
        command += ["-d"]
    command += [image]

    # DEVNULL is only in py3
    try:
        from subprocess import DEVNULL
    except ImportError:
        DEVNULL = open(os.devnull, "wb")  # noqa: N806
    code = subprocess.call(command, stdout=DEVNULL)
    if daemon:
        if code != 0:
            wandb.termerror(
                "Failed to launch the W&B server container, see the above error."
            )
            exit(1)
        else:
            wandb.termlog("W&B server started at http://localhost:%s \U0001F680" % port)
            wandb.termlog("You can stop the server by running `wandb server stop`")
            if not api.api_key:
                # Let the server start before potentially launching a browser
                time.sleep(2)
                ctx.invoke(login, host=host)


@server.command(
    context_settings={
        "default_map": {},
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
    help="Stop a local W&B server",
)
def stop():
    if not find_executable("docker"):
        raise ClickException("Docker not installed, install it from https://docker.com")
    subprocess.call(["docker", "stop", "wandb-local"])
