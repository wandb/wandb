import json
import pprint
from typing import Any, Dict, List, Optional, Union

import wandb
from wandb.apis.internal import Api
import wandb.apis.public as public
from wandb.sdk.launch.utils import construct_launch_spec, validate_launch_spec_source


def push_to_queue(api: Api, queue: str, launch_spec: Dict[str, Any]) -> Any:
    try:
        res = api.push_to_run_queue(queue, launch_spec)
    except Exception as e:
        print("Exception:", e)
        return None
    return res


def launch_add(
    uri: Optional[str] = None,
    job: Optional[str] = None,
    config: Optional[Union[str, Dict[str, Any]]] = None,
    project: Optional[str] = None,
    entity: Optional[str] = None,
    queue: Optional[str] = None,
    resource: Optional[str] = None,
    entry_point: Optional[List[str]] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    docker_image: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    resource_args: Optional[Dict[str, Any]] = None,
    cuda: Optional[bool] = None,
    run_id: Optional[str] = None,
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
        queue,
        resource,
        entry_point,
        name,
        version,
        docker_image,
        params,
        resource_args,
        cuda,
        run_id=run_id,
    )


def _launch_add(
    api: Api,
    uri: Optional[str],
    job: Optional[str],
    config: Optional[Union[str, Dict[str, Any]]],
    project: Optional[str],
    entity: Optional[str],
    queue: Optional[str],
    resource: Optional[str],
    entry_point: Optional[List[str]],
    name: Optional[str],
    version: Optional[str],
    docker_image: Optional[str],
    params: Optional[Dict[str, Any]],
    resource_args: Optional[Dict[str, Any]] = None,
    cuda: Optional[bool] = None,
    run_id: Optional[str] = None,
) -> "public.QueuedRun":

    resource = resource or "local"
    if config is not None:
        if isinstance(config, str):
            with open(config) as fp:
                launch_config = json.load(fp)
        elif isinstance(config, dict):
            launch_config = config
    else:
        launch_config = {}

    if queue is None:
        queue = "default"

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
        launch_config,
        cuda,
        run_id,
    )
    validate_launch_spec_source(launch_spec)
    res = push_to_queue(api, queue, launch_spec)

    if res is None or "runQueueItemId" not in res:
        raise Exception("Error adding run to queue")
    wandb.termlog(f"Added run to queue {queue}.")
    wandb.termlog(f"Launch spec:\n{pprint.pformat(launch_spec)}\n")
    public_api = public.Api()
    queued_run_entity = launch_spec.get("entity")
    queued_run_project = launch_spec.get("project")
    container_job = False
    if job:
        job_artifact = public_api.job(job)
        if job_artifact._source_info.get("source_type") == "image":
            container_job = True

    queued_run = public_api.queued_run(
        queued_run_entity,
        queued_run_project,
        queue,
        res["runQueueItemId"],
        container_job,
    )
    return queued_run  # type: ignore
