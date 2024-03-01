import logging

import click

import wandb
from wandb.cli.utils.api import _get_cling_api
from wandb.cli.utils.errors import display_error
from wandb.sdk.launch import utils as launch_utils
from wandb.sdk.launch.errors import LaunchError

logger = logging.getLogger(__name__)


@click.command(
    name="launch_agent",
    context_settings={"default_map": {}},
    help="Run a W&B launch agent.",
)
@click.pass_context
@click.option(
    "--queue",
    "-q",
    "queues",
    default=None,
    multiple=True,
    metavar="<queue(s)>",
    help="The name of a queue for the agent to watch. Multiple -q flags supported.",
)
@click.option(
    "--project",
    "-p",
    default=None,
    help="""Name of the project which the agent will watch.
    If passed in, will override the project value passed in using a config file.""",
)
@click.option(
    "--entity",
    "-e",
    default=None,
    help="The entity to use. Defaults to current logged-in user",
)
@click.option(
    "--log-file",
    "-l",
    default=None,
    help=(
        "Destination for internal agent logs. Use - for stdout. "
        "By default all agents logs will go to debug.log in your wandb/ "
        "subdirectory or WANDB_DIR if set."
    ),
)
@click.option(
    "--max-jobs",
    "-j",
    default=None,
    help="The maximum number of launch jobs this agent can run in parallel. Defaults to 1. Set to -1 for no upper limit",
)
@click.option(
    "--config", "-c", default=None, help="path to the agent config yaml to use"
)
@click.option(
    "--url",
    "-u",
    default=None,
    hidden=True,
    help="a wandb client registration URL, this is generated in the UI",
)
@display_error
def launch_agent(
    ctx,
    project=None,
    entity=None,
    queues=None,
    max_jobs=None,
    config=None,
    url=None,
    log_file=None,
):
    logger.info(
        f"=== Launch-agent called with kwargs {locals()}  CLI Version: {wandb.__version__} ==="
    )
    if url is not None:
        raise LaunchError(
            "--url is not supported in this version, upgrade with: pip install -u wandb"
        )

    import wandb.sdk.launch._launch as _launch

    if log_file is not None:
        _launch.set_launch_logfile(log_file)

    api = _get_cling_api()
    wandb._sentry.configure_scope(process_context="launch_agent")
    agent_config, api = _launch.resolve_agent_config(
        entity, project, max_jobs, queues, config
    )

    if len(agent_config.get("queues")) == 0:
        raise LaunchError(
            "To launch an agent please specify a queue or a list of queues in the configuration file or cli."
        )

    launch_utils.check_logged_in(api)

    wandb.termlog("Starting launch agent ✨")
    try:
        _launch.create_and_run_agent(api, agent_config)
    except Exception as e:
        wandb._sentry.exception(e)
        raise e
