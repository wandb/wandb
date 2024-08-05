import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import yaml

import wandb
from wandb.apis.internal import Api

from . import loader
from ._project_spec import LaunchProject
from .agent import LaunchAgent
from .agent.agent import construct_agent_configs
from .environment.local_environment import LocalEnvironment
from .errors import ExecutionError, LaunchError
from .runner.abstract import AbstractRun
from .utils import (
    LAUNCH_CONFIG_FILE,
    PROJECT_SYNCHRONOUS,
    construct_launch_spec,
    validate_launch_spec_source,
)

_logger = logging.getLogger(__name__)


def set_launch_logfile(logfile: str) -> None:
    """Set the logfile for the launch agent."""
    # Get logger of parent module
    _launch_logger = logging.getLogger("wandb.sdk.launch")
    if logfile == "-":
        logfile_stream = sys.stdout
    else:
        try:
            logfile_stream = open(logfile, "w")
        # check if file is writable
        except Exception as e:
            wandb.termerror(
                f"Could not open {logfile} for writing logs. Please check "
                f"the path and permissions.\nError: {e}"
            )
            return

    wandb.termlog(
        f"Internal agent logs printing to {'stdout' if logfile == '-' else logfile}. "
    )
    handler = logging.StreamHandler(logfile_stream)
    handler.formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(threadName)-10s:%(process)d "
        "[%(filename)s:%(funcName)s():%(lineno)s] %(message)s"
    )
    _launch_logger.addHandler(handler)
    _launch_logger.log(logging.INFO, "Internal agent logs printing to %s", logfile)


def resolve_agent_config(  # noqa: C901
    entity: Optional[str],
    max_jobs: Optional[int],
    queues: Optional[Tuple[str]],
    config: Optional[str],
    verbosity: Optional[int],
) -> Tuple[Dict[str, Any], Api]:
    """Resolve the agent config.

    Arguments:
        api (Api): The api.
        entity (str): The entity.
        max_jobs (int): The max number of jobs.
        queues (Tuple[str]): The queues.
        config (str): The config.
        verbosity (int): How verbose to print, 0 or None = default, 1 = print status every 20 seconds, 2 = also print debugging information

    Returns:
        Tuple[Dict[str, Any], Api]: The resolved config and api.
    """
    defaults = {
        "max_jobs": 1,
        "max_schedulers": 1,
        "queues": [],
        "registry": {},
        "builder": {},
        "verbosity": 0,
    }
    resolved_config: Dict[str, Any] = defaults
    config_path = config or os.path.expanduser(LAUNCH_CONFIG_FILE)
    if os.path.isfile(config_path):
        launch_config = {}
        with open(config_path) as f:
            try:
                launch_config = yaml.safe_load(f)
                # This is considered unreachable by mypy, but it's not.
                if launch_config is None:
                    launch_config = {}  # type: ignore
            except yaml.YAMLError as e:
                raise LaunchError(f"Invalid launch agent config: {e}")
        resolved_config.update(launch_config.items())
    elif config is not None:
        raise LaunchError(
            f"Could not find use specified launch config file: {config_path}"
        )
    if os.environ.get("WANDB_ENTITY") is not None:
        resolved_config.update({"entity": os.environ.get("WANDB_ENTITY")})
    if os.environ.get("WANDB_LAUNCH_MAX_JOBS") is not None:
        resolved_config.update(
            {"max_jobs": int(os.environ.get("WANDB_LAUNCH_MAX_JOBS", 1))}
        )

    if entity is not None:
        resolved_config.update({"entity": entity})
    if max_jobs is not None:
        resolved_config.update({"max_jobs": int(max_jobs)})
    if queues:
        resolved_config.update({"queues": list(queues)})
    if verbosity:
        resolved_config.update({"verbosity": int(verbosity)})
    # queue -> queues
    if resolved_config.get("queue"):
        if isinstance(resolved_config.get("queue"), str):
            resolved_config["queues"].append(resolved_config["queue"])
        else:
            raise LaunchError(
                f"Invalid launch agent config for key 'queue' with type: {type(resolved_config.get('queue'))}"
                + " (expected str). Specify multiple queues with the 'queues' key"
            )

    keys = ["entity"]
    settings = {
        k: resolved_config.get(k) for k in keys if resolved_config.get(k) is not None
    }

    api = Api(default_settings=settings)

    if resolved_config.get("entity") is None:
        resolved_config.update({"entity": api.default_entity})

    return resolved_config, api


def create_and_run_agent(
    api: Api,
    config: Dict[str, Any],
) -> None:
    try:
        from wandb.sdk.launch.agent import config as agent_config
    except ModuleNotFoundError:
        raise LaunchError(
            "wandb launch-agent requires pydantic to be installed. "
            "Please install with `pip install wandb[launch]`"
        )
    try:
        agent_config.AgentConfig(**config)
    except agent_config.ValidationError as e:
        errors = e.errors()
        for error in errors:
            loc = ".".join([str(x) for x in error.get("loc", [])])
            msg = f"Agent config error in field {loc}"
            value = error.get("input")
            if not isinstance(value, dict):
                msg += f" (value: {value})"
            msg += f": {error['msg']}"
            wandb.termerror(msg)
        raise LaunchError("Invalid launch agent config")
    agent = LaunchAgent(api, config)
    try:
        asyncio.run(agent.loop())
    except asyncio.CancelledError:
        pass


async def _launch(
    api: Api,
    job: Optional[str] = None,
    name: Optional[str] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    docker_image: Optional[str] = None,
    entry_point: Optional[List[str]] = None,
    version: Optional[str] = None,
    resource: Optional[str] = None,
    resource_args: Optional[Dict[str, Any]] = None,
    launch_config: Optional[Dict[str, Any]] = None,
    synchronous: Optional[bool] = None,
    run_id: Optional[str] = None,
    repository: Optional[str] = None,
) -> AbstractRun:
    """Helper that delegates to the project-running method corresponding to the passed-in backend."""
    if launch_config is None:
        launch_config = {}
    if resource is None:
        resource = "local-container"
    launch_spec = construct_launch_spec(
        None,
        job,
        api,
        name,
        project,
        entity,
        docker_image,
        resource,
        entry_point,
        version,
        resource_args,
        launch_config,
        run_id,
        repository,
        author=None,
    )
    validate_launch_spec_source(launch_spec)
    launch_project = LaunchProject.from_spec(launch_spec, api)
    launch_project.fetch_and_validate_project()
    entrypoint = launch_project.get_job_entry_point()
    image_uri = (
        launch_project.docker_image or launch_project.job_base_image
    )  # Either set by user or None.

    # construct runner config.
    runner_config: Dict[str, Any] = {}
    runner_config[PROJECT_SYNCHRONOUS] = synchronous

    config = launch_config or {}
    environment_config, build_config, registry_config = construct_agent_configs(config)
    environment = loader.environment_from_config(environment_config)
    if environment is not None and not isinstance(environment, LocalEnvironment):
        await environment.verify()
    registry = loader.registry_from_config(registry_config, environment)
    builder = loader.builder_from_config(build_config, environment, registry)
    if not (launch_project.docker_image or launch_project.job_base_image):
        assert entrypoint
        image_uri = await builder.build_image(launch_project, entrypoint, None)
    backend = loader.runner_from_config(
        resource, api, runner_config, environment, registry
    )
    if backend:
        assert image_uri
        submitted_run = await backend.run(launch_project, image_uri)
        # this check will always pass, run is only optional in the agent case where
        # a run queue id is present on the backend config
        assert submitted_run
        return submitted_run
    else:
        raise ExecutionError(
            f"Unavailable backend {resource}, available backends: {', '.join(loader.WANDB_RUNNERS)}"
        )


def launch(
    api: Api,
    job: Optional[str] = None,
    entry_point: Optional[List[str]] = None,
    version: Optional[str] = None,
    name: Optional[str] = None,
    resource: Optional[str] = None,
    resource_args: Optional[Dict[str, Any]] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    docker_image: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    synchronous: Optional[bool] = True,
    run_id: Optional[str] = None,
    repository: Optional[str] = None,
) -> AbstractRun:
    """Launch a W&B launch experiment.

    Arguments:
        job: string reference to a wandb.Job eg: wandb/test/my-job:latest
        api: An instance of a wandb Api from wandb.apis.internal.
        entry_point: Entry point to run within the project. Defaults to using the entry point used
            in the original run for wandb URIs, or main.py for git repository URIs.
        version: For Git-based projects, either a commit hash or a branch name.
        name: Name run under which to launch the run.
        resource: Execution backend for the run.
        resource_args: Resource related arguments for launching runs onto a remote backend.
            Will be stored on the constructed launch config under ``resource_args``.
        project: Target project to send launched run to
        entity: Target entity to send launched run to
        config: A dictionary containing the configuration for the run. May also contain
        resource specific arguments under the key "resource_args".
        synchronous: Whether to block while waiting for a run to complete. Defaults to True.
            Note that if ``synchronous`` is False and ``backend`` is "local-container", this
            method will return, but the current process will block when exiting until
            the local run completes. If the current process is interrupted, any
            asynchronous runs launched via this method will be terminated. If
            ``synchronous`` is True and the run fails, the current process will
            error out as well.
        run_id: ID for the run (To ultimately replace the :name: field)
        repository: string name of repository path for remote registry

    Example:
        ```python
        from wandb.sdk.launch import launch

        job = "wandb/jobs/Hello World:latest"
        params = {"epochs": 5}
        # Run W&B project and create a reproducible docker environment
        # on a local host
        api = wandb.apis.internal.Api()
        launch(api, job, parameters=params)
        ```


    Returns:
        an instance of`wandb.launch.SubmittedRun` exposing information (e.g. run ID)
        about the launched run.

    Raises:
        `wandb.exceptions.ExecutionError` If a run launched in blocking mode
        is unsuccessful.
    """
    submitted_run_obj = asyncio.run(
        _launch(
            job=job,
            name=name,
            project=project,
            entity=entity,
            docker_image=docker_image,
            entry_point=entry_point,
            version=version,
            resource=resource,
            resource_args=resource_args,
            launch_config=config,
            synchronous=synchronous,
            api=api,
            run_id=run_id,
            repository=repository,
        )
    )

    return submitted_run_obj
