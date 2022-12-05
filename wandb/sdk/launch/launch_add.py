import pprint
from typing import Any, Dict, List, Optional

import wandb
import wandb.apis.public as public
from wandb.apis.internal import Api
from wandb.errors import LaunchError
from wandb.sdk.launch._project_spec import create_project_from_spec
from wandb.sdk.launch.builder.build import build_image_from_project
from wandb.sdk.launch.utils import (
    LOG_PREFIX,
    construct_launch_spec,
    validate_launch_spec_source,
)


def push_to_queue(api: Api, queue_name: str, launch_spec: Dict[str, Any]) -> Any:
    try:
        res = api.push_to_run_queue(queue_name, launch_spec)
    except Exception as e:
        wandb.termwarn(f"{LOG_PREFIX}Exception when pushing to queue {e}")
        return None
    return res


def launch_add(
    uri: Optional[str] = None,
    job: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    queue_name: Optional[str] = None,
    resource: Optional[str] = None,
    entry_point: Optional[List[str]] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    docker_image: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    resource_args: Optional[Dict[str, Any]] = None,
    cuda: Optional[bool] = None,
    run_id: Optional[str] = None,
    build: Optional[bool] = False,
    repository: Optional[str] = None,
) -> "public.QueuedRun":
    """Enqueue a W&B launch experiment. With either a source uri, job or docker_image.

    Arguments:
    uri: URI of experiment to run. A wandb run uri or a Git repository URI.
    job: string reference to a wandb.Job eg: wandb/test/my-job:latest
    config: A dictionary containing the configuration for the run. May also contain
        resource specific arguments under the key "resource_args"
    project: Target project to send launched run to
    entity: Target entity to send launched run to
    queue: the name of the queue to enqueue the run to
    resource: Execution backend for the run: W&B provides built-in support for "local" backend
    entry_point: Entry point to run within the project. Defaults to using the entry point used
        in the original run for wandb URIs, or main.py for git repository URIs.
    name: Name run under which to launch the run.
    version: For Git-based projects, either a commit hash or a branch name.
    docker_image: The name of the docker image to use for the run.
    params: Parameters (dictionary) for the entry point command. Defaults to using the
        the parameters used to run the original run.
    resource_args: Resource related arguments for launching runs onto a remote backend.
        Will be stored on the constructed launch config under ``resource_args``.
    cuda: Whether to build a CUDA-enabled docker image or not
    run_id: optional string indicating the id of the launched run
    build: optional flag defaulting to false, requires queue to be set
        if build, an image is created, creates a job artifact, pushes a reference
            to that job artifact to queue
    repository: optional string to control the name of the remote repository, used when
        pushing images to a registry


    Example:
        import wandb
        project_uri = "https://github.com/wandb/examples"
        params = {"alpha": 0.5, "l1_ratio": 0.01}
        # Run W&B project and create a reproducible docker environment
        # on a local host
        api = wandb.apis.internal.Api()
        wandb.launch_add(uri=project_uri, parameters=params)


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
        uri,
        job,
        config,
        project,
        entity,
        queue_name,
        resource,
        entry_point,
        name,
        version,
        docker_image,
        params,
        resource_args,
        cuda,
        run_id=run_id,
        build=build,
        repository=repository,
    )


def _launch_add(
    api: Api,
    uri: Optional[str],
    job: Optional[str],
    config: Optional[Dict[str, Any]],
    project: Optional[str],
    entity: Optional[str],
    queue_name: Optional[str],
    resource: Optional[str],
    entry_point: Optional[List[str]],
    name: Optional[str],
    version: Optional[str],
    docker_image: Optional[str],
    params: Optional[Dict[str, Any]],
    resource_args: Optional[Dict[str, Any]] = None,
    cuda: Optional[bool] = None,
    run_id: Optional[str] = None,
    build: Optional[bool] = False,
    repository: Optional[str] = None,
) -> "public.QueuedRun":
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
        params,
        resource_args,
        config,
        cuda,
        run_id,
        repository,
    )

    if build:
        if launch_spec.get("job") is not None:
            wandb.termwarn("Build doesn't support setting a job. Overwriting job.")
            launch_spec["job"] = None

        launch_project = create_project_from_spec(launch_spec, api)
        docker_image_uri = build_image_from_project(launch_project, api, config)
        run = wandb.run or wandb.init(
            project=launch_spec["project"],
            entity=launch_spec["entity"],
            job_type="launch_job",
        )

        job_artifact = run._log_job_artifact_with_image(docker_image_uri)
        job_name = job_artifact.wait().name

        job = f"{launch_spec['entity']}/{launch_spec['project']}/{job_name}"
        launch_spec["job"] = job
        launch_spec["uri"] = None  # Remove given URI --> now in job

    if queue_name is None:
        queue_name = "default"

    validate_launch_spec_source(launch_spec)
    res = push_to_queue(api, queue_name, launch_spec)

    if res is None or "runQueueItemId" not in res:
        raise LaunchError("Error adding run to queue")
    wandb.termlog(f"{LOG_PREFIX}Added run to queue {queue_name}.")
    wandb.termlog(f"{LOG_PREFIX}Launch spec:\n{pprint.pformat(launch_spec)}\n")
    public_api = public.Api()
    container_job = False
    if job:
        job_artifact = public_api.job(job)
        if job_artifact._source_info.get("source_type") == "image":
            container_job = True

    queued_run = public_api.queued_run(
        launch_spec["entity"],
        launch_spec["project"],
        queue_name,
        res["runQueueItemId"],
        container_job,
    )
    return queued_run  # type: ignore
