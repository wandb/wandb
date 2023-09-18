import json
from typing import Any, Dict, List, Optional, Union

import click
import yaml

import wandb
from wandb.apis import InternalApi, PublicApi
from wandb.sdk.launch import utils as launch_utils
from wandb.sdk.launch.sweeps.scheduler import Scheduler
from wandb.sdk.launch.sweeps.utils import (
    check_job_exists,
    construct_scheduler_args,
    get_previous_args,
    handle_sweep_config_violations,
)


def launch_sweep(
    entity: str,
    project: str,
    queue: str,
    config: Optional[Dict[str, Any]] = None,
    resume_id: Optional[str] = None,
) -> Optional[str]:
    """Create a sweep and launch it on a remote resource queue.

    Arguments:
        entity (str): The entity to launch the sweep under
        project (str): The project to launch the sweep under
        queue (str): The queue name to launch the sweep to
        config (Optional[Dict[str, Any]]): a dictionary of sweep and launch config parameters
        resume_id (Optional[str]): The id of the sweep to resume

    Returns:
        str: The sweep id of the launched sweep

    Example:
        config = {
            "job": "wandb/sweep-jobs/job-fashion-MNIST-train:latest",
            "method": "grid",
            "run_cap": 2,
            "parameters": {
                "learning_rate": {
                    "values": [0.01, 0.1]
                },
                "batch_size": {
                    "values": [32, 64]
                },
            },
            "scheduler": {
                "num_workers": 2,
                "resource": "local-container"
            },
            "launch": {
                "resource_args": {
                    "local-container": {
                        "env": ["WANDB_BASE_URL", "WANDB_SILENT"]
                    }
                }
            }
        }

        sweep_id = launch_sweep(
            entity="wandb",
            project="fashion-mnist",
            queue="aks-x64-CPU-gigantic",
            config=config
        )
    """
    api = InternalApi()

    return _launch_sweep(
        api=api,
        entity=entity,
        project=project,
        queue=queue,
        parsed_user_config=config,
        resume_id=resume_id,
    )


def _launch_sweep(
    api: InternalApi,
    entity: str,
    project: str,
    queue: str,
    parsed_user_config: Optional[Dict[str, Any]] = None,
    resume_id: Optional[str] = None,
) -> Optional[str]:
    if not (parsed_user_config or resume_id):
        wandb.termerror("'config' and/or 'resume_id' required")
        return None

    parsed_user_config = parsed_user_config or {}
    # get personal username, not team name or service account, default to entity
    author = api.viewer().get("username") or entity

    # Rip special keys out of config, store in scheduler run_config
    launch_args: Dict[str, Any] = parsed_user_config.pop("launch", {})
    scheduler_args: Dict[str, Any] = parsed_user_config.pop("scheduler", {})
    settings: Dict[str, Any] = scheduler_args.pop("settings", {})

    scheduler_job: Optional[str] = scheduler_args.get("job")
    if not queue and isinstance(launch_args.get("queue"), str):
        queue = launch_args["queue"]

    sweep_config, sweep_obj_id = {}, None
    if not resume_id:
        sweep_config = parsed_user_config

        # check method
        method = sweep_config.get("method")
        if scheduler_job and not method:
            sweep_config["method"] = "custom"
        elif scheduler_job and method != "custom":
            # TODO(gst): Check if using Anaconda2
            wandb.termwarn(
                "Use 'method': 'custom' in the sweep config when using scheduler jobs, "
                "or omit it entirely. For jobs using the wandb optimization engine (wandb/sweep-jobs/job-wandb-sweep-scheduler) "
                "set the method in the sweep config under scheduler.settings.method "
            )
            settings["method"] = method
        if settings.get("method"):
            # assume wandb/sweep-jobs/job-wandb-sweep-scheduler, and user is using this right
            sweep_config["method"] = settings["method"]

    else:  # Resuming an existing sweep
        found = api.sweep(resume_id, "{}", entity=entity, project=project)
        if not found:
            wandb.termerror(f"Could not find sweep {entity}/{project}/{resume_id}")
            return None

        if found.get("state") == "RUNNING":
            wandb.termerror(
                f"Cannot resume sweep {entity}/{project}/{resume_id}, it is already running"
            )
            return None

        sweep_obj_id = found["id"]
        sweep_config = yaml.safe_load(found["config"])
        wandb.termlog(f"Resuming from existing sweep {entity}/{project}/{resume_id}")
        if len(parsed_user_config.keys()) > 0:
            wandb.termwarn(
                "Sweep parameters loaded from resumed sweep, ignoring provided config"
            )

        prev_scheduler = json.loads(found.get("scheduler") or "{}")
        run_spec = json.loads(prev_scheduler.get("run_spec", "{}"))
        if (
            scheduler_job
            and run_spec.get("job")
            and run_spec.get("job") != scheduler_job
        ):
            wandb.termerror(
                f"Resuming a launch sweep with a different scheduler job is not supported. Job loaded from sweep: {run_spec.get('job')}, job in config: {scheduler_job}"
            )
            return None

        prev_scheduler_args, prev_settings = get_previous_args(run_spec)
        # Passed in scheduler_args and settings override previous
        scheduler_args.update(prev_scheduler_args)
        settings.update(prev_settings)

    if not queue:
        wandb.termerror(
            "Launch-sweeps require setting a 'queue', use --queue option or a 'queue' key in the 'launch' section in the config"
        )
        return None

    # validate training job existence
    if not check_job_exists(PublicApi(), sweep_config.get("job")):
        return None

    # validate scheduler job existence, if present
    if not check_job_exists(PublicApi(), scheduler_job):
        return None

    assert sweep_config, "required"

    entrypoint = Scheduler.ENTRYPOINT if not scheduler_job else None
    args = construct_scheduler_args(
        return_job=scheduler_job is not None,
        sweep_config=sweep_config,
        queue=queue,
        project=project,
        author=author,
    )
    if not args:
        return None

    # set name of scheduler
    name = scheduler_args.get("name") or "Scheduler.WANDB_SWEEP_ID"
    if scheduler_args.get("name"):
        settings["name"] = name

    # Set run overrides for the Scheduler
    overrides = _make_scheduler_overrides(
        launch_args,
        scheduler_args,
        settings,
        scheduler_job,
        args,
    )

    # configure scheduler job resource
    resource = _handle_resource(scheduler_args, scheduler_job)
    if not resource:
        return None

    # Launch job spec for the Scheduler
    launch_scheduler_spec = launch_utils.construct_launch_spec(
        uri=Scheduler.PLACEHOLDER_URI,
        api=api,
        name=name,
        project=project,
        entity=entity,
        docker_image=scheduler_args.get("docker_image"),
        resource=resource,
        entry_point=entrypoint,
        resource_args=scheduler_args.get("resource_args", {}),
        repository=launch_args.get("registry", {}).get("url", None),
        job=scheduler_job,
        version=None,
        launch_config={"overrides": overrides},
        run_id="WANDB_SWEEP_ID",  # scheduler inits run with sweep_id=run_id
        author=None,  # author gets passed into scheduler override args
    )
    launch_scheduler_with_queue = json.dumps(
        {
            "queue": queue,
            "run_queue_project": launch_utils.LAUNCH_DEFAULT_PROJECT,
            "run_spec": json.dumps(launch_scheduler_spec),
        }
    )

    sweep_id, warnings = api.upsert_sweep(
        sweep_config,
        project=project,
        entity=entity,
        obj_id=sweep_obj_id,  # if resuming
        launch_scheduler=launch_scheduler_with_queue,
        state="PENDING",
    )
    handle_sweep_config_violations(warnings)
    assert isinstance(sweep_id, str)  # mypy

    # Log nicely formatted sweep information
    styled_id = click.style(sweep_id, fg="yellow")
    wandb.termlog(f"{'Resumed' if resume_id else 'Created'} sweep with ID: {styled_id}")
    return sweep_id


def _make_scheduler_overrides(
    launch_args: Optional[Dict[str, Any]],
    scheduler_args: Optional[Dict[str, Any]],
    settings: Optional[Dict[str, Any]],
    scheduler_job: Optional[str],
    args: Union[List[str], Dict[str, str]],
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {"run_config": {}}
    if launch_args:
        overrides["run_config"]["launch"] = launch_args
    if scheduler_args:
        overrides["run_config"]["scheduler"] = scheduler_args
    if settings:
        overrides["run_config"]["settings"] = settings
    if scheduler_job:
        assert isinstance(args, Dict)
        overrides["run_config"]["sweep_args"] = args
    else:
        assert isinstance(args, List)
        overrides["args"] = args
    return overrides


def _handle_resource(
    scheduler_args: Dict[str, Any], scheduler_job: Optional[str]
) -> Optional[str]:
    """Helper to determine resource from scheduler args."""
    if scheduler_args.get("resource"):
        resource = scheduler_args["resource"]
        if not isinstance(resource, str):
            wandb.termerror(
                "Scheduler resource must be a string, e.g. 'local-container'"
            )
            return None
        if resource == "local-process" and scheduler_job:
            wandb.termerror(
                "Scheduler jobs cannot be run with the 'local-process' resource"
            )
            return None
        if resource == "local-process" and scheduler_args.get("docker_image"):
            wandb.termerror(
                "Scheduler jobs cannot be run with the 'local-process' resource and a docker image"
            )
            return None
        return resource
    # no resource set, default local-process if not scheduler job, else container
    return "local-process" if not scheduler_job else "local-container"
