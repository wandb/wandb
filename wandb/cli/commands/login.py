import sys

import click

import wandb
from wandb import wandb_sdk
from wandb.cli.utils.errors import display_error


@click.command(
    name="login",
    context_settings={"default_map": {}},
    help="Login to Weights & Biases",
)
@click.argument("key", nargs=-1)
@click.option("--cloud", is_flag=True, help="Login to the cloud instead of local")
@click.option("--host", default=None, help="Login to a specific instance of W&B")
@click.option(
    "--relogin", default=None, is_flag=True, help="Force relogin if already logged in."
)
@click.option("--anonymously", default=False, is_flag=True, help="Log in anonymously")
@click.option("--verify", default=False, is_flag=True, help="Verify login credentials")
@display_error
def login(key, host, cloud, relogin, anonymously, verify, no_offline=False):
    # TODO: handle no_offline
    anon_mode = "must" if anonymously else "never"

    wandb_sdk.wandb_login._handle_host_wandb_setting(host, cloud)
    # A change in click or the test harness means key can be none...
    key = key[0] if key is not None and len(key) > 0 else None
    if key:
        relogin = True

    login_settings = dict(
        _cli_only_mode=True,
        _disable_viewer=relogin and not verify,
        anonymous=anon_mode,
    )
    if host is not None:
        login_settings["base_url"] = host

    try:
        wandb.setup(settings=login_settings)
    except TypeError as e:
        wandb.termerror(str(e))
        sys.exit(1)

    wandb.login(
        relogin=relogin,
        key=key,
        anonymous=anon_mode,
        host=host,
        force=True,
        verify=verify,
    )
