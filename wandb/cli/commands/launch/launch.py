import asyncio
import logging
import shlex
import sys
import traceback

import click

import wandb
from wandb import util
from wandb.apis import PublicApi
from wandb.apis.public import RunQueue
from wandb.cli.utils.api import _get_cling_api
from wandb.cli.utils.errors import display_error
from wandb.sdk.launch import utils as launch_utils
from wandb.sdk.launch._launch_add import _launch_add
from wandb.sdk.launch.errors import ExecutionError, LaunchError
from wandb.sdk.lib.wburls import wburls

logger = logging.getLogger(__name__)


@click.command(
    name="launch",
    help=f"Launch or queue a W&B Job. See {wburls.get('cli_launch')}",
)
@click.option("--uri", "-u", metavar="(str)", default=None, hidden=True)
@click.option(
    "--job",
    "-j",
    metavar="(str)",
    default=None,
    help="Name of the job to launch. If passed in, launch does not require a uri.",
)
@click.option(
    "--entry-point",
    "-E",
    metavar="NAME",
    default=None,
    help="""Entry point within project. [default: main]. If the entry point is not found,
    attempts to run the project file with the specified name as a script,
    using 'python' to run .py files and the default shell (specified by
    environment variable $SHELL) to run .sh files. If passed in, will override the entrypoint value passed in using a config file.""",
)
@click.option(
    "--git-version",
    "-g",
    metavar="GIT-VERSION",
    hidden=True,
    help="Version of the project to run, as a Git commit reference for Git projects.",
)
@click.option(
    "--name",
    envvar="WANDB_NAME",
    help="""Name of the run under which to launch the run. If not
    specified, a random run name will be used to launch run. If passed in, will override the name passed in using a config file.""",
)
@click.option(
    "--entity",
    "-e",
    metavar="(str)",
    default=None,
    help="""Name of the target entity which the new run will be sent to. Defaults to using the entity set by local wandb/settings folder.
    If passed in, will override the entity value passed in using a config file.""",
)
@click.option(
    "--project",
    "-p",
    metavar="(str)",
    default=None,
    help="""Name of the target project which the new run will be sent to. Defaults to using the project name given by the source uri
    or for github runs, the git repo name. If passed in, will override the project value passed in using a config file.""",
)
@click.option(
    "--resource",
    "-r",
    metavar="BACKEND",
    default=None,
    help="""Execution resource to use for run. Supported values: 'local-process', 'local-container', 'kubernetes', 'sagemaker', 'gcp-vertex'.
    This is now a required parameter if pushing to a queue with no resource configuration.
    If passed in, will override the resource value passed in using a config file.""",
)
@click.option(
    "--docker-image",
    "-d",
    default=None,
    metavar="DOCKER IMAGE",
    help="""Specific docker image you'd like to use. In the form name:tag.
    If passed in, will override the docker image value passed in using a config file.""",
)
@click.option(
    "--config",
    "-c",
    metavar="FILE",
    help="""Path to JSON file (must end in '.json') or JSON string which will be passed
    as a launch config. Dictation how the launched run will be configured.""",
)
@click.option(
    "--set-var",
    "-v",
    "cli_template_vars",
    default=None,
    multiple=True,
    help="""Set template variable values for queues with allow listing enabled,
    as key-value pairs e.g. `--set-var key1=value1 --set-var key2=value2`""",
)
@click.option(
    "--queue",
    "-q",
    is_flag=False,
    flag_value="default",
    default=None,
    help="""Name of run queue to push to. If none, launches single run directly. If supplied without
    an argument (`--queue`), defaults to queue 'default'. Else, if name supplied, specified run queue must exist under the
    project and entity supplied.""",
)
@click.option(
    "--async",
    "run_async",
    is_flag=True,
    help="""Flag to run the job asynchronously. Defaults to false, i.e. unless --async is set, wandb launch will wait for
    the job to finish. This option is incompatible with --queue; asynchronous options when running with an agent should be
    set on wandb launch-agent.""",
)
@click.option(
    "--resource-args",
    "-R",
    metavar="FILE",
    help="""Path to JSON file (must end in '.json') or JSON string which will be passed
    as resource args to the compute resource. The exact content which should be
    provided is different for each execution backend. See documentation for layout of this file.""",
)
@click.option(
    "--build",
    "-b",
    is_flag=True,
    hidden=True,
    help="Flag to build an associated job and push to queue as an image job.",
)
@click.option(
    "--repository",
    "-rg",
    is_flag=False,
    default=None,
    hidden=True,
    help="Name of a remote repository. Will be used to push a built image to.",
)
# TODO: this is only included for back compat. But we should remove this in the future
@click.option(
    "--project-queue",
    "-pq",
    default=None,
    hidden=True,
    help="Name of the project containing the queue to push to. If none, defaults to entity level queues.",
)
@click.option(
    "--dockerfile",
    "-D",
    default=None,
    help="Path to the Dockerfile used to build the job, relative to the job's root",
)
@click.option(
    "--priority",
    "-P",
    default=None,
    type=click.Choice(["critical", "high", "medium", "low"]),
    help="""When --queue is passed, set the priority of the job. Launch jobs with higher priority
    are served first.  The order, from highest to lowest priority, is: critical, high, medium, low""",
)
@display_error
def launch(  # noqa: C901
    uri,
    job,
    entry_point,
    git_version,
    name,
    resource,
    entity,
    project,
    docker_image,
    config,
    cli_template_vars,
    queue,
    run_async,
    resource_args,
    build,
    repository,
    project_queue,
    dockerfile,
    priority,
):
    """Start a W&B run from the given URI.

    The URI can bea wandb URI, a GitHub repo uri, or a local path). In the case of a
    wandb URI the arguments used in the original run will be used by default. These
    arguments can be overridden using the args option, or specifying those arguments in
    the config's 'overrides' key, 'args' field as a list of strings.

    Running `wandb launch [URI]` will launch the run directly. To add the run to a
    queue, run `wandb launch [URI] --queue [optional queuename]`.
    """
    logger.info(
        f"=== Launch called with kwargs {locals()} CLI Version: {wandb.__version__}==="
    )
    from wandb.sdk.launch._launch import _launch

    api = _get_cling_api()
    wandb._sentry.configure_scope(process_context="launch_cli")

    if run_async and queue is not None:
        raise LaunchError(
            "Cannot use both --async and --queue with wandb launch, see help for details."
        )

    if queue and docker_image and not project:
        raise LaunchError(
            "Cannot use --queue and --docker together without a project. Please specify a project with --project or -p."
        )

    if priority is not None and queue is None:
        raise LaunchError("--priority flag requires --queue to be set")

    if resource_args is not None:
        resource_args = util.load_json_yaml_dict(resource_args)
        if resource_args is None:
            raise LaunchError("Invalid format for resource-args")
    else:
        resource_args = {}

    if entry_point is not None:
        entry_point = shlex.split(entry_point)

    if config is not None:
        config = util.load_json_yaml_dict(config)
        if config is None:
            raise LaunchError("Invalid format for config")
    else:
        config = {}

    resource = resource or config.get("resource")

    if build and queue is None:
        raise LaunchError("Build flag requires a queue to be set")

    try:
        launch_utils.check_logged_in(api)
    except Exception:
        wandb.termerror(f"Error running job: {traceback.format_exc()}")

    run_id = config.get("run_id")

    if dockerfile:
        if "overrides" in config:
            config["overrides"]["dockerfile"] = dockerfile
        else:
            config["overrides"] = {"dockerfile": dockerfile}

    if priority is not None:
        priority_map = {
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 3,
        }
        priority = priority_map[priority.lower()]

    template_variables = None
    if cli_template_vars:
        if queue is None:
            raise LaunchError("'--set-var' flag requires queue to be set")
        if entity is None:
            entity = launch_utils.get_default_entity(api, config)
        public_api = PublicApi()
        runqueue = RunQueue(client=public_api.client, name=queue, entity=entity)
        template_variables = launch_utils.fetch_and_validate_template_variables(
            runqueue, cli_template_vars
        )

    if queue is None:
        # direct launch
        try:
            run = asyncio.run(
                _launch(
                    api,
                    uri,
                    job,
                    project=project,
                    entity=entity,
                    docker_image=docker_image,
                    name=name,
                    entry_point=entry_point,
                    version=git_version,
                    resource=resource,
                    resource_args=resource_args,
                    launch_config=config,
                    synchronous=(not run_async),
                    run_id=run_id,
                    repository=repository,
                )
            )
            if asyncio.run(run.get_status()).state in [
                "failed",
                "stopped",
                "preempted",
            ]:
                wandb.termerror("Launched run exited with non-zero status")
                sys.exit(1)
        except LaunchError as e:
            logger.error("=== %s ===", e)
            wandb._sentry.exception(e)
            sys.exit(e)
        except ExecutionError as e:
            logger.error("=== %s ===", e)
            wandb._sentry.exception(e)
            sys.exit(e)
        except asyncio.CancelledError:
            sys.exit(0)
    else:
        try:
            _launch_add(
                api,
                uri,
                job,
                config,
                template_variables,
                project,
                entity,
                queue,
                resource,
                entry_point,
                name,
                git_version,
                docker_image,
                project_queue,
                resource_args,
                build=build,
                run_id=run_id,
                repository=repository,
                priority=priority,
            )

        except Exception as e:
            wandb._sentry.exception(e)
            raise e
