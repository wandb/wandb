import asyncio
import pprint
from typing import Any, Dict, List, Optional, Union

import wandb
import wandb.apis.public as public
from wandb.apis.internal import Api
from wandb.errors import CommError
from wandb.sdk.launch.builder.build import build_image_from_project
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    LAUNCH_DEFAULT_PROJECT,
    LOG_PREFIX,
    construct_launch_spec,
    validate_launch_spec_source,
)

from ._project_spec import LaunchProject


def push_to_queue(
    api: Api,
    queue_name: str,
    launch_spec: Dict[str, Any],
    template_variables: Optional[dict],
    project_queue: str,
    priority: Optional[int] = None,
) -> Any:
    return api.push_to_run_queue(
        queue_name, launch_spec, template_variables, project_queue, priority
    )


def launch_add(
    uri: Optional[str] = None,
    job: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    template_variables: Optional[Dict[str, Union[float, int, str]]] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    queue_name: Optional[str] = None,
    resource: Optional[str] = None,
    entry_point: Optional[List[str]] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    docker_image: Optional[str] = None,
    project_queue: Optional[str] = None,
    resource_args: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    build: Optional[bool] = False,
    repository: Optional[str] = None,
    sweep_id: Optional[str] = None,
    author: Optional[str] = None,
    priority: Optional[int] = None,
) -> "public.QueuedRun":
    """Enqueue a W&B launch experiment. With either a source uri, job or docker_image.

    Arguments:
        uri: URI of experiment to run. A wandb run uri or a Git repository URI.
        job: string reference to a wandb.Job eg: wandb/test/my-job:latest
        config: A dictionary containing the configuration for the run. May also contain
            resource specific arguments under the key "resource_args"
        template_variables: A dictionary containing values of template variables for a run queue.
            Expected format of {"VAR_NAME": VAR_VALUE}
        project: Target project to send launched run to
        entity: Target entity to send launched run to
        queue: the name of the queue to enqueue the run to
        priority: the priority level of the job, where 1 is the highest priority
        resource: Execution backend for the run: W&B provides built-in support for "local-container" backend
        entry_point: Entry point to run within the project. Defaults to using the entry point used
            in the original run for wandb URIs, or main.py for git repository URIs.
        name: Name run under which to launch the run.
        version: For Git-based projects, either a commit hash or a branch name.
        docker_image: The name of the docker image to use for the run.
        resource_args: Resource related arguments for launching runs onto a remote backend.
            Will be stored on the constructed launch config under ``resource_args``.
        run_id: optional string indicating the id of the launched run
        build: optional flag defaulting to false, requires queue to be set
            if build, an image is created, creates a job artifact, pushes a reference
                to that job artifact to queue
        repository: optional string to control the name of the remote repository, used when
            pushing images to a registry
        project_queue: optional string to control the name of the project for the queue. Primarily used
            for back compatibility with project scoped queues


    Example:
    ```python
    from wandb.sdk.launch import launch_add

    project_uri = "https://github.com/wandb/examples"
    params = {"alpha": 0.5, "l1_ratio": 0.01}
    # Run W&B project and create a reproducible docker environment
    # on a local host
    api = wandb.apis.internal.Api()
    launch_add(uri=project_uri, parameters=params)
    ```


    Returns:
        an instance of`wandb.api.public.QueuedRun` which gives information about the
        queued run, or if `wait_until_started` or `wait_until_finished` are called, gives access
        to the underlying Run information.

    Raises:
        `wandb.exceptions.LaunchError` if unsuccessful
    """
    api = Api()

    return _launch_add(
        api,
        job,
        config,
        template_variables,
        project,
        entity,
        queue_name,
        resource,
        entry_point,
        name,
        version,
        docker_image,
        project_queue,
        resource_args,
        run_id=run_id,
        build=build,
        repository=repository,
        sweep_id=sweep_id,
        author=author,
        priority=priority,
    )


def _launch_add(
    api: Api,
    job: Optional[str],
    config: Optional[Dict[str, Any]],
    template_variables: Optional[dict],
    project: Optional[str],
    entity: Optional[str],
    queue_name: Optional[str],
    resource: Optional[str],
    entry_point: Optional[List[str]],
    name: Optional[str],
    version: Optional[str],
    docker_image: Optional[str],
    project_queue: Optional[str],
    resource_args: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    build: Optional[bool] = False,
    repository: Optional[str] = None,
    sweep_id: Optional[str] = None,
    author: Optional[str] = None,
    priority: Optional[int] = None,
) -> "public.QueuedRun":
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
        config,
        run_id,
        repository,
        author,
        sweep_id,
    )

    if build:
        if resource == "local-process":
            raise LaunchError(
                "Cannot build a docker image for the resource: local-process"
            )

        if launch_spec.get("job") is not None:
            wandb.termwarn("Build doesn't support setting a job. Overwriting job.")
            launch_spec["job"] = None

        launch_project = LaunchProject.from_spec(launch_spec, api)
        docker_image_uri = asyncio.run(
            build_image_from_project(launch_project, api, config or {})
        )
        run = wandb.run or wandb.init(
            project=launch_spec["project"],
            entity=launch_spec["entity"],
            job_type="launch_job",
        )

        job_artifact = run._log_job_artifact_with_image(  # type: ignore
            docker_image_uri, launch_project.override_args
        )
        job_name = job_artifact.wait().name

        job = f"{launch_spec['entity']}/{launch_spec['project']}/{job_name}"
        launch_spec["job"] = job
        launch_spec["uri"] = None  # Remove given URI --> now in job

    if queue_name is None:
        queue_name = "default"
    if project_queue is None:
        project_queue = LAUNCH_DEFAULT_PROJECT
    spec_template_vars = launch_spec.get("template_variables")
    if isinstance(spec_template_vars, dict):
        launch_spec.pop("template_variables")
        if template_variables is None:
            template_variables = spec_template_vars
        else:
            template_variables = {
                **spec_template_vars,
                **template_variables,
            }

    validate_launch_spec_source(launch_spec)
    res = push_to_queue(
        api, queue_name, launch_spec, template_variables, project_queue, priority
    )

    if res is None or "runQueueItemId" not in res:
        raise LaunchError("Error adding run to queue")

    updated_spec = res.get("runSpec")
    if updated_spec:
        if updated_spec.get("resource_args"):
            launch_spec["resource_args"] = updated_spec.get("resource_args")
        if updated_spec.get("resource"):
            launch_spec["resource"] = updated_spec.get("resource")

    if project_queue == LAUNCH_DEFAULT_PROJECT:
        wandb.termlog(f"{LOG_PREFIX}Added run to queue {queue_name}.")
    else:
        wandb.termlog(f"{LOG_PREFIX}Added run to queue {project_queue}/{queue_name}.")
    wandb.termlog(f"{LOG_PREFIX}Launch spec:\n{pprint.pformat(launch_spec)}\n")

    public_api = public.Api()
    if job is not None:
        try:
            public_api.artifact(job, type="job")
        except (ValueError, CommError) as e:
            raise LaunchError(f"Unable to fetch job with name {job}: {e}")

    queued_run = public_api.queued_run(
        launch_spec["entity"],
        launch_spec["project"],
        queue_name,
        res["runQueueItemId"],
        project_queue,
        priority,
    )
    return queued_run  # type: ignore
