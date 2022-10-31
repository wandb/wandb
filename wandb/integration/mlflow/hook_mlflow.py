import difflib
import functools
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import click
import mlflow
import requests
import wandb


JSON = Dict[str, Any]
MLflow_Response = Optional[requests.Response]


RUN_INFO = None


def _get_mlflow_run_tags(response: MLflow_Response) -> List[JSON]:
    if not response:
        return []
    body = response.json()
    run = body.get("run", {})
    data = run.get("data", {})
    tags = data.get("tags", [])
    return tags


def _mlflow_tags_to_wandb_tags(mlflow_tags) -> List[str]:
    tags = []
    for mlflow_tag in mlflow_tags:
        key = mlflow_tag.get("key")
        if key == "mlflow.runName":
            # We'll set the name of the W&B Run
            continue
        if key in ("mlflow.source.name", "mlflow.source.git.commit"):
            # W&B will capture these itself
            continue
        value = mlflow_tag.get("value")
        tag = f"{key}={value}"
        if len(tag) > 64:
            wandb.termwarn(
                f"MLflow tag is too long ({len(tag)} > 64) to store in W&B: {tag}"
            )
        else:
            tags.append(tag)
    return tags


def _wandb_tags_to_mlflow_tags(run) -> List[Dict[str, str]]:
    tags = []
    for wandb_tag in run.tags:
        key, value = wandb_tag.split("=", 1)
        mlflow_tag = {
            "key": key,
            "value": value,
        }
        tags.append(mlflow_tag)

    # Yuck. Is there a better way?
    commit = wandb.run._commit
    tags.append({"key": "mlflow.source.git.commit", "value": commit})

    tags.append({"key": "mlflow.runName", "value": run.name})
    return tags


def _wandb_config_to_mlflow_params(run) -> List[Dict[str, str]]:
    params = []
    for key, value in run.config.as_dict().items():
        params.append(
            {
                "key": key,
                "value": value,
            }
        )
    return params


def _wandb_run_to_mlflow_response(run):
    metrics = []
    params = _wandb_config_to_mlflow_params(run)
    tags = _wandb_tags_to_mlflow_tags(run)
    data = {
        "metrics": metrics,
        "params": params,
        "tags": tags,
    }
    global RUN_INFO
    response = {
        "run": {
            "data": data,
            "info": RUN_INFO,
        },
    }
    return response


def _get_mlflow_run_name(response: MLflow_Response) -> Optional[str]:
    tags = _get_mlflow_run_tags(response)
    if not tags:
        return None
    name_obj = next(t for t in tags if t.get("key") == "mlflow.runName")
    return name_obj.get("value")


def get_json(request: JSON):
    return request.get("json", {})


def run_create(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    body = get_json(request)
    # print(json.dumps(body, indent=4))

    name = _get_mlflow_run_name(response)
    tags = _mlflow_tags_to_wandb_tags(_get_mlflow_run_tags(response))
    wandb.run.name = name
    wandb.run.tags = wandb.run.tags + tuple(tags)

    experiment_id = body.get("experiment_id", "0")
    user_id = body.get("user_id", "")
    wandb_start_time = round(wandb.run.start_time * 1000)
    artifact_uri = f"file://{os.path.dirname(wandb.run.dir)}/mlflow_artifacts"
    start_time = body.get("start_time", wandb_start_time)
    response_tags = body.get("tags", [])
    response_tags.append({"key": "mlflow.runName", "value": name})
    global RUN_INFO
    RUN_INFO = {
        "artifact_uri": artifact_uri,
        "experiment_id": experiment_id,
        "lifecycle_stage": "active",
        "run_id": wandb.run.id,
        "run_name": name,
        "run_uuid": wandb.run.id,
        "start_time": start_time,
        "status": "RUNNING",
        "user_id": user_id,
    }
    our_response = {
        "run": {
            "data": {"tags": response_tags},
            "info": RUN_INFO,
        }
    }
    return 200, our_response


def run_update(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    body = get_json(request)
    status = body.get("status")
    global RUN_INFO
    if status == "FINISHED":
        # TODO: Where can I get W&B's view of end time?
        RUN_INFO["end_time"] = round(time.time() * 1000)
        RUN_INFO["status"] = "FINISHED"
        try:
            wandb.finish()
        except BrokenPipeError:
            # We've probably already logged run end
            pass
    else:
        print(click.style(f"IN UPDATE RUN UNHANDLED STATUS {status}", fg="red"))

    our_response = {"run_info": RUN_INFO}
    return 200, our_response


def run_log_batch(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    body = get_json(request)
    if "params" in body:
        for param in body["params"]:
            key = param["key"]
            value = param["value"]
            wandb.run.config[key] = value

    if "metrics" in body:
        # Metrics can be from different steps
        metrics = body["metrics"]
        step_data = {}
        for metric in metrics:
            step = metric["step"]
            if step not in step_data:
                step_data[step] = {}
            key = metric["key"]
            value = metric["value"]
            step_data[step][key] = value
        for step, data in step_data.items():
            wandb.run.log(data, step=step)

    if "tags" in body:
        mlflow_tags = body["tags"]
        wandb_tags = _mlflow_tags_to_wandb_tags(mlflow_tags)
        wandb.run.tags += tuple(wandb_tags)

    return 200, {}


def run_log_parameter(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    body = get_json(request)
    run_id = body.get("run_id")
    key = body.get("key")
    value = body.get("value")
    wandb.run.config[key] = value
    return 200, {}


def run_log_metric(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    body = get_json(request)
    # print(json.dumps(body, indent=4))
    key = body.get("key")
    value = body.get("value")
    # TODO: Can we use this
    timestamp = body.get("timestamp")
    step = body.get("step")
    data = {}
    data[key] = value
    wandb.run.log(data, step=step)
    return 200, {}


def run_log_model(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    # print("log_model")
    # Not clear what this request is used for, it appears the content gets logged as an MLmodel YAML artifact.
    body = get_json(request)
    print(json.dumps(body, indent=4))
    return 200, {}


def run_get(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    params = request.get("params", {})
    run_id = params.get("run_id")
    our_response = {}
    if not run_id:
        print(click.style("NOT GETTING OTHER THAN BY ID YET", fg="red"))
    else:
        our_response = _wandb_run_to_mlflow_response(wandb.run)
    return 200, our_response


def process_runs(
    path: str, request: JSON, response: Optional[requests.Response]
) -> Tuple[int, JSON]:
    if path == "create":
        return run_create(request, response)
    if path == "update":
        return run_update(request, response)
    if path == "log-batch":
        return run_log_batch(request, response)
    if path == "log-parameter":
        return run_log_parameter(request, response)
    if path == "log-metric":
        return run_log_metric(request, response)
    if path == "log-model":
        return run_log_model(request, response)
    if path == "get":
        return run_get(request, response)
    print("NOT HANDLED IN RUNS " + path)
    return 200, {}


def registered_model_create(
    request: JSON, response: MLflow_Response
) -> Tuple[int, JSON]:
    # TODO: I don't believe we have an SDK method for this yet.
    # https://www.notion.so/wandbai/Create-Portfolio-via-SDK-f80420b855bd41a18d01106585172f4e
    print("registered model create")
    print(json.dumps(request, indent=4))
    body = get_json(request)
    name = body.get("name")
    print(name)
    # art = wandb.Artifact(name, type="model")
    # wandb.log_artifact(art)
    return 200, {}


def process_registered_models(
    path: str, request: JSON, response: MLflow_Response
) -> Tuple[int, JSON]:
    print("in process_registered_models")
    print(path)
    if path == "create":
        return registered_model_create(request, response)
    print("NOT HANDLED IN REGISTERED MODELS " + path)
    return 200, {}


def model_version_create(request: JSON, response: MLflow_Response) -> Tuple[int, JSON]:
    print("model version create")
    # print(json.dumps(request, indent=4))
    body = get_json(request)
    name = body.get("name")
    source = body.get("source")
    print(name)
    print(source)
    tail = os.path.basename(source)
    if tail in LOGGED_ARTIFACTS:
        print(
            click.style(
                "SHOULD LINK ARTIFACT BUT THAT API IS NOT YET IMPLEMENTED", fg="yellow"
            )
        )
        # LOGGED_ARTIFACTS[tail].link(name)
    else:
        print(
            click.style(
                "WARNING: WHICH ARTIFACT TO CREATE MODEL VERSION FROM?", fg="yellow"
            )
        )
    return 200, {}


def process_model_versions(
    path: str, request: JSON, response: MLflow_Response
) -> Tuple[int, JSON]:
    print("in process_model_versions")
    print(path)
    if path == "create":
        return model_version_create(request, response)
    print(click.style(f"NOT HANDLED IN MODEL VERSIONS {path}", fg="red"))
    return 200, {}


def compare_responses(our_response, mlflow_response):
    if mlflow_response is None:
        # No MLflow server to compare with
        return

    print(mlflow_response.request.url)
    our_status_code = our_response.status_code
    our_body = our_response.json()
    if our_status_code == mlflow_response.status_code:
        print(click.style(f"STATUS CODE MATCH: {our_status_code}", fg="green"))
    else:
        print(
            click.style(
                f"STATUS CODES NO MATCH {our_status_code} != {mlflow_response.status_code}",
                fg="magenta",
            )
        )

    str_our = json.dumps(our_body, indent=4, sort_keys=True)
    str_mlflow = json.dumps(mlflow_response.json(), indent=4, sort_keys=True)
    if str_our == str_mlflow:
        print(click.style("RESPONSE MATCH", fg="green"))
    else:
        print(click.style("RESPONSE NO MATCH", fg="magenta"))
        our_split = str_our.split("\n")
        mlflow_split = str_mlflow.split("\n")
        n = max(len(our_split), len(mlflow_split))
        for diff in difflib.unified_diff(
            our_split, mlflow_split, n=n, lineterm="", fromfile="wandb", tofile="mlflow"
        ):
            if diff.startswith("-"):
                print(click.style(diff, fg="cyan"))
            elif diff.startswith("+"):
                print(click.style(diff, fg="magenta"))
            else:
                print(diff)


def process_transaction(method, url, response, **kwargs):
    # Paths might look like:
    # http://127.0.0.1:10002/api/2.0/mlflow/runs/log-metric
    # http://127.0.0.1:10002/api/2.0/preview/mlflow/registered-models/create
    split_path = url.split("/")
    (
        protocol,
        _,
        host_and_port,
        api,
        api_version,
        mlflow_or_preview_constant,
        *path_components,
    ) = split_path
    response_tuple = (200, {})
    api_path = "/".join(path_components)
    if api_path.startswith("runs/"):
        response_tuple = process_runs(api_path[5:], kwargs, response)
    elif api_path.startswith("mlflow/registered-models/"):
        response_tuple = process_registered_models(api_path[25:], kwargs, response)
    elif api_path.startswith("mlflow/model-versions/"):
        response_tuple = process_model_versions(api_path[22:], kwargs, response)
    else:
        print("NOT HANDLED IN PROCESS_TRANSACTION")
        print(method)
        print(url)
        print(api)
        print(api_version)
        print(mlflow_or_preview_constant)
        print(api_path)

    our_response = MagicMock()
    our_response.status_code = response_tuple[0]
    our_response.json.return_value = response_tuple[1]
    our_response.text = json.dumps(response_tuple[1])
    compare_responses(our_response, response)
    return our_response


def get_http_response_with_retries(
    method, url, max_retries, backoff_factor, retry_codes, **kwargs
):
    """
    Performs an HTTP request using Python's `requests` module with an automatic retry policy.

    :param method: a string indicating the method to use, e.g. "GET", "POST", "PUT".
    :param url: the target URL address for the HTTP request.
    :param max_retries: Maximum total number of retries.
    :param backoff_factor: a time factor for exponential backoff. e.g. value 5 means the HTTP
      request will be retried with interval 5, 10, 20... seconds. A value of 0 turns off the
      exponential backoff.
    :param retry_codes: a list of HTTP response error codes that qualifies for retry.
    :param kwargs: Additional keyword arguments to pass to `requests.Session.request()`

    :return: requests.Response object.
    """
    print(url)
    our_response = response = None
    if not url.startswith("https://wandb.ai"):  # TODO: What about on-prem
        # TODO: Is this the same for all MLflow versions?
        session = mlflow.utils.rest_utils._get_request_session(
            max_retries, backoff_factor, retry_codes
        )
        response = session.request(method, url, **kwargs)
    try:
        our_response = process_transaction(method, url, response, **kwargs)
    except Exception as exc:
        print("JCR: Unhandled Exception in process_transaction")
        print(exc)
        raise
    return response if response else our_response


LOGGED_ARTIFACTS = {}


def log_artifact(self, run_id, local_path, artifact_path=None) -> None:
    # TODO: Default includes the path prepended with "run-<id>-" - do we want that prefix?
    artifact_type = "model" if artifact_path == "model" else "mlflow"
    artifact = wandb.run.log_artifact(local_path, type=artifact_type)
    if artifact_path:
        LOGGED_ARTIFACTS[artifact_path] = artifact


def log_artifacts(
    self, run_id: str, local_dir: str, artifact_path: Optional[str] = None
) -> None:
    artifact_type = "model" if artifact_path == "model" else "mlflow"
    artifact = wandb.run.log_artifact(local_dir, type=artifact_type)
    if artifact_path:
        LOGGED_ARTIFACTS[artifact_path] = artifact


# Call our hook with the same arguments
def hook_function(target_function, hook):
    @functools.wraps(target_function)
    def run(*args, **kwargs):
        hook(*args, **kwargs)
        return target_function(*args, **kwargs)

    return run


def hook_mlflow(mlflow):
    wandb.termlog("MLflow found, hooking HTTP calls for W&B logging.")
    mlflow.utils.rest_utils._get_http_response_with_retries = (
        get_http_response_with_retries
    )
    client = mlflow.tracking.client.MlflowClient
    client.log_artifact = hook_function(client.log_artifact, log_artifact)
    client.log_artifacts = hook_function(client.log_artifacts, log_artifacts)
