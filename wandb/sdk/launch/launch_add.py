import json
from typing import Any, Dict
import sys

import wandb
import wandb.apis.public as public
from wandb.apis.internal import Api
from wandb.sdk.launch.utils import construct_launch_spec, set_project_entity_defaults


def push_to_queue(api: Api, queue: str, launch_spec: Dict[str, Any]) -> Any:
    try:
        res = api.push_to_run_queue(queue, launch_spec)
    except Exception as e:
        print("Exception:", e)
        return None
    return res


def launch_add(
    uri: str = None,
    config: Dict[str, Any] = None,
    project: str = None,
    entity: str = None,
    queue: str = None,
    resource: str = None,
    entry_point: str = None,
    name: str = None,
    version: str = None,
    docker_image: str = None,
    params: Dict[str, Any] = None,
):
    api = Api()
    return _launch_add(
        api,
        uri,
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
    )


def _launch_add(
    api: Api,
    uri: str,
    config: Dict[str, Any],
    project: str,
    entity: str,
    queue: str,
    resource: str,
    entry_point: str,
    name: str,
    version: str,
    docker_image: str,
    params: Dict[str, Any],
):

    resource = resource or "local"
    if config is not None:
        with open(config, "r") as f:
            launch_config = json.load(f)
    else:
        launch_config = {}

    project, entity, _ = set_project_entity_defaults(
        uri,
        project or launch_config.get("project"),
        entity or launch_config.get("entity"),
        api,
    )

    launch_spec = construct_launch_spec(
        uri,
        name,
        project,
        entity,
        docker_image,
        entry_point,
        version,
        params,
        launch_config,
    )
    print(launch_spec)
    res = push_to_queue(api, queue, launch_spec)
    if res is None or "runQueueItemId" not in res:
        raise Exception("Error adding run to queue")
    wandb.termlog("Added run to queue")
    public_api = public.Api()
    queued_job = public_api.queued_job(
        f"{entity}/{project}/{queue}/{res['runQueueItemId']}"
    )
    return queued_job
