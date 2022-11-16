import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml

from wandb.apis.internal import Api
from wandb.errors import ExecutionError, LaunchError

from ._project_spec import create_project_from_spec, fetch_and_validate_project
from .agent import LaunchAgent
from .builder import loader as builder_loader
from .builder.build import construct_builder_args
from .runner import loader
from .runner.abstract import AbstractRun
from .utils import (
    LAUNCH_CONFIG_FILE,
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
    construct_launch_spec,
    validate_launch_spec_source,
)

_logger = logging.getLogger(__name__)


def resolve_agent_config(
    api: Api,
    entity: Optional[str],
    project: Optional[str],
    max_jobs: Optional[int],
    queues: Optional[List[str]],
) -> Tuple[Dict[str, Any], Api]:
    defaults = {
        "entity": api.default_entity,
        "max_jobs": 1,
        "queues": ["default"],
        "api_key": api.api_key,
        "base_url": api.settings("base_url"),
        "registry": {},
        "build": {},
        "runner": {},
    }

    resolved_config: Dict[str, Any] = defaults
    if os.path.exists(os.path.expanduser(LAUNCH_CONFIG_FILE)):
        config = {}
        with open(os.path.expanduser(LAUNCH_CONFIG_FILE)) as f:
            try:
                config = yaml.safe_load(f)
                print(config)
            except yaml.YAMLError as e:
                raise LaunchError(f"Invalid launch agent config: {e}")
        resolved_config.update(dict(config))
    if os.environ.get("WANDB_PROJECT") is not None:
        resolved_config.update({"project": os.environ.get("WANDB_PROJECT")})
    if os.environ.get("WANDB_ENTITY") is not None:
        resolved_config.update({"entity": os.environ.get("WANDB_ENTITY")})
    if os.environ.get("WANDB_API_KEY") is not None:
        resolved_config.update({"api_key": os.environ.get("WANDB_API_KEY")})
    if os.environ.get("WANDB_LAUNCH_MAX_JOBS") is not None:
        resolved_config.update(
            {"max_jobs": int(os.environ.get("WANDB_LAUNCH_MAX_JOBS", 1))}
        )
    if os.environ.get("WANDB_BASE_URL") is not None:
        resolved_config.update({"base_url": os.environ.get("WANDB_BASE_URL")})

    if project is not None:
        resolved_config.update({"project": project})
    if entity is not None:
        resolved_config.update({"entity": entity})
    if max_jobs is not None:
        resolved_config.update({"max_jobs": int(max_jobs)})

    if queues is not None:
        resolved_config.update({"queues": queues})
    if (
        resolved_config["entity"] != defaults["entity"]
        or resolved_config["api_key"] != defaults["api_key"]
        or resolved_config["base_url"] != defaults["base_url"]
    ):
        settings = dict(
            api_key=resolved_config["api_key"],
            base_url=resolved_config["base_url"],
            project=resolved_config["project"],
            entity=resolved_config["entity"],
        )
        api = Api(default_settings=settings)

    return resolved_config, api


def create_and_run_agent(
    api: Api,
    config: Dict[str, Any],
) -> None:
    agent = LaunchAgent(api, config)
    agent.loop()


def _run(
    uri: Optional[str],
    job: Optional[str],
    name: Optional[str],
    project: Optional[str],
    entity: Optional[str],
    docker_image: Optional[str],
    entry_point: Optional[List[str]],
    version: Optional[str],
    parameters: Optional[Dict[str, Any]],
    resource: str,
    resource_args: Optional[Dict[str, Any]],
    launch_config: Optional[Dict[str, Any]],
    synchronous: Optional[bool],
    cuda: Optional[bool],
    api: Api,
    run_id: Optional[str],
    repository: Optional[str],
) -> AbstractRun:
    """Helper that delegates to the project-running method corresponding to the passed-in backend."""
    launch_spec = construct_launch_spec(
        uri,
        job,
        api,
        name,
        project,
        entity,
        docker_image,
        resource,
        entry_point,
        version,
        parameters,
        resource_args,
        launch_config,
        cuda,
        run_id,
        repository,
    )
    validate_launch_spec_source(launch_spec)
    launch_project = create_project_from_spec(launch_spec, api)
    launch_project = fetch_and_validate_project(launch_project, api)

    # construct runner config.
    runner_config: Dict[str, Any] = {}
    runner_config[PROJECT_SYNCHRONOUS] = synchronous

    if repository:  # override existing registry with CLI arg
        launch_config = launch_config or {}
        registry = launch_config.get("registry", {})
        registry["url"] = repository
        launch_config["registry"] = registry

    given_docker_args, build_config, registry_config = construct_builder_args(
        launch_config,
    )

    runner_config[PROJECT_DOCKER_ARGS] = given_docker_args

    builder = builder_loader.load_builder(build_config)
    backend = loader.load_backend(resource, api, runner_config)
    if backend:
        submitted_run = backend.run(launch_project, builder, registry_config)
        # this check will always pass, run is only optional in the agent case where
        # a run queue id is present on the backend config
        assert submitted_run
        return submitted_run
    else:
        raise ExecutionError(
            f"Unavailable backend {resource}, available backends: {', '.join(loader.WANDB_RUNNERS)}"
        )


def run(
    api: Api,
    uri: Optional[str] = None,
    job: Optional[str] = None,
    entry_point: Optional[List[str]] = None,
    version: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
    resource: str = "local",
    resource_args: Optional[Dict[str, Any]] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    docker_image: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    synchronous: Optional[bool] = True,
    cuda: Optional[bool] = None,
    run_id: Optional[str] = None,
    repository: Optional[str] = None,
) -> AbstractRun:
    """Run a W&B launch experiment. The project can be wandb uri or a Git URI.

    Arguments:
    uri: URI of experiment to run. A wandb run uri or a Git repository URI.
    job: string reference to a wandb.Job eg: wandb/test/my-job:latest
    api: An instance of a wandb Api from wandb.apis.internal.
    entry_point: Entry point to run within the project. Defaults to using the entry point used
        in the original run for wandb URIs, or main.py for git repository URIs.
    version: For Git-based projects, either a commit hash or a branch name.
    parameters: Parameters (dictionary) for the entry point command. Defaults to using the
        the parameters used to run the original run.
    name: Name run under which to launch the run.
    resource: Execution backend for the run: W&B provides built-in support for "local" backend
    resource_args: Resource related arguments for launching runs onto a remote backend.
        Will be stored on the constructed launch config under ``resource_args``.
    project: Target project to send launched run to
    entity: Target entity to send launched run to
    config: A dictionary containing the configuration for the run. May also contain
    resource specific arguments under the key "resource_args".
    synchronous: Whether to block while waiting for a run to complete. Defaults to True.
        Note that if ``synchronous`` is False and ``backend`` is "local", this
        method will return, but the current process will block when exiting until
        the local run completes. If the current process is interrupted, any
        asynchronous runs launched via this method will be terminated. If
        ``synchronous`` is True and the run fails, the current process will
        error out as well.
    cuda: Whether to build a CUDA-enabled docker image or not
    run_id: ID for the run (To ultimately replace the :name: field)
    repository: string name of repository path for remote registry

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
    if config is None:
        config = {}

    submitted_run_obj = _run(
        uri=uri,
        job=job,
        name=name,
        project=project,
        entity=entity,
        docker_image=docker_image,
        entry_point=entry_point,
        version=version,
        parameters=parameters,
        resource=resource,
        resource_args=resource_args,
        launch_config=config,
        synchronous=synchronous,
        cuda=cuda,
        api=api,
        run_id=run_id,
        repository=repository,
    )

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
