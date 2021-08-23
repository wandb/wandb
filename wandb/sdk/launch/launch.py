import logging
import sys
from typing import Any, Dict, List, Optional

from wandb.apis.internal import Api
from wandb.errors import ExecutionError, LaunchError

from ._project_spec import create_project_from_spec, fetch_and_validate_project
from .agent import LaunchAgent
from .runner import loader
from .runner.abstract import AbstractRun
from .utils import (
    _is_wandb_local_uri,
    construct_launch_spec,
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)

_logger = logging.getLogger(__name__)


def run_agent(entity: str, project: str, queues: Optional[List[str]] = None) -> None:
    agent = LaunchAgent(entity, project, queues)
    agent.loop()


def _run(
    uri: str,
    name: Optional[str],
    project: Optional[str],
    entity: Optional[str],
    docker_image: Optional[str],
    entry_point: Optional[str],
    version: Optional[str],
    parameters: Optional[Dict[str, Any]],
    docker_args: Optional[Dict[str, Any]],
    resource: str,
    launch_config: Optional[Dict[str, Any]],
    synchronous: Optional[bool],
    api: Api,
) -> AbstractRun:
    """Helper that delegates to the project-running method corresponding to the passed-in backend."""
    launch_spec = construct_launch_spec(
        uri,
        api,
        name,
        project,
        entity,
        docker_image,
        entry_point,
        version,
        parameters,
        launch_config,
    )
    launch_project = create_project_from_spec(launch_spec, api)
    launch_project = fetch_and_validate_project(launch_project, api)

    # construct runner config.
    runner_config: Dict[str, Any] = {}
    runner_config[PROJECT_SYNCHRONOUS] = synchronous
    runner_config[PROJECT_DOCKER_ARGS] = docker_args

    backend = loader.load_backend(resource, api, runner_config)
    if backend:
        submitted_run = backend.run(launch_project)
        # this check will always pass, run is only optional in the agent case where
        # a run queue id is present on the backend config
        assert submitted_run
        return submitted_run
    else:
        raise ExecutionError(
            "Unavailable backend {}, available backends: {}".format(
                resource, ", ".join(loader.WANDB_RUNNERS.keys())
            )
        )


def run(
    uri: str,
    api: Api,
    entry_point: Optional[str] = None,
    version: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    docker_args: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    resource: str = "local",
    project: Optional[str] = None,
    entity: Optional[str] = None,
    docker_image: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    synchronous: Optional[bool] = True,
) -> AbstractRun:
    """Run a W&B launch experiment. The project can be wandb uri or a Git URI.

    Arguments:
    uri: URI of experiment to run. A wandb run uri or a Git repository URI.
    api: An instance of a wandb Api from wandb.apis.internal.
    entry_point: Entry point to run within the project. Defaults to using the entry point used
        in the original run for wandb URIs, or main.py for git repository URIs.
    version: For Git-based projects, either a commit hash or a branch name.
    parameters: Parameters (dictionary) for the entry point command. Defaults to using the
        the parameters used to run the original run.
    docker_args: Arguments (dictionary) for the docker command.
    name: Name run under which to launch the run.
    resource: Execution backend for the run: W&B provides built-in support for "local" backend
    project: Target project to send launched run to
    entity: Target entity to send launched run to
    config: A dictionary which will be passed as config to the backend. The exact content
        which should be provided is different for each execution backend
    synchronous: Whether to block while waiting for a run to complete. Defaults to True.
        Note that if ``synchronous`` is False and ``backend`` is "local", this
        method will return, but the current process will block when exiting until
        the local run completes. If the current process is interrupted, any
        asynchronous runs launched via this method will be terminated. If
        ``synchronous`` is True and the run fails, the current process will
        error out as well.


    Example:
        import wandb
        project_uri = "https://github.com/wandb/examples"
        params = {"alpha": 0.5, "l1_ratio": 0.01}
        # Run W&B project and create a reproducible docker environment
        # on a local host
        api = wandb.apis.internal.Api()
        wandb.launch(project_uri, api, parameters=params)


    Returns:
        an instance of`wandb.launch.SubmittedRun` exposing information (e.g. run ID)
        about the launched run.

    Raises:
        `wandb.exceptions.ExecutionError` If a run launched in blocking mode
        is unsuccessful.
    """
    if docker_args is None:
        docker_args = {}

    if _is_wandb_local_uri(api.settings("base_url")):
        if sys.platform == "win32":
            docker_args["net"] = "host"
        else:
            docker_args["network"] = "host"
        if sys.platform == "linux" or sys.platform == "linux2":
            docker_args["add-host"] = "host.docker.internal:host-gateway"

    if config is None:
        config = {}

    submitted_run_obj = _run(
        uri=uri,
        name=name,
        project=project,
        entity=entity,
        docker_image=docker_image,
        entry_point=entry_point,
        version=version,
        parameters=parameters,
        docker_args=docker_args,
        resource=resource,
        launch_config=config,
        synchronous=synchronous,
        api=api,
    )

    if synchronous:
        _wait_for(submitted_run_obj)
    else:
        raise LaunchError("Non synchronous mode not supported")
    return submitted_run_obj


def _wait_for(submitted_run_obj: AbstractRun) -> None:
    """Wait on the passed-in submitted run, reporting its status to the tracking server."""
    # Note: there's a small chance we fail to report the run's status to the tracking server if
    # we're interrupted before we reach the try block below
    try:
        if submitted_run_obj.wait():
            _logger.info("=== Submitted run succeeded ===")
        else:
            raise ExecutionError("Submitted run failed")
    except KeyboardInterrupt:
        _logger.error("=== Submitted run interrupted, cancelling run ===")
        submitted_run_obj.cancel()
        raise
