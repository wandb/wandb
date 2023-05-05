import json

import pytest
import wandb
from wandb.apis.public import Api as PublicApi
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.sweeps.scheduler import Scheduler
from wandb.sdk.launch.utils import construct_launch_spec


@pytest.mark.parametrize(
    "resource",
    ["local-process", None],
)
def test_sweeps_on_launch(
    relay_server, user, wandb_init, test_settings, resource, monkeypatch
):
    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    monkeypatch.setattr(
        wandb.docker,
        "build",
        lambda tags, file, context_path: None,
    )

    monkeypatch.setattr(
        wandb.docker,
        "push",
        lambda reg, tag: None,
    )

    proj = "test_project2"
    queue = "existing-queue"
    settings = test_settings({"project": proj})

    with relay_server():
        wandb_init(settings=settings).finish()

        api = wandb.sdk.internal.internal_api.Api()
        api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

        sweep_config = {
            "job": "fake-job:v1",
            "method": "bayes",
            "metric": {
                "name": "loss_metric",
                "goal": "minimize",
            },
            "parameters": {
                "epochs": {"value": 1},
                "increment": {"values": [0.1, 0.2, 0.3]},
            },
        }

        # Launch job spec for the Scheduler
        _launch_scheduler_spec = json.dumps(
            {
                "queue": queue,
                "run_spec": json.dumps(
                    construct_launch_spec(
                        Scheduler.PLACEHOLDER_URI,  # uri
                        None,  # job
                        api,
                        "Scheduler.WANDB_SWEEP_ID",  # name,
                        proj,
                        user,
                        None,  # docker_image,
                        resource,  # resource,
                        [
                            "wandb",
                            "scheduler",
                            "WANDB_SWEEP_ID",
                            "--queue",
                            queue,
                            "--project",
                            proj,
                            "--job",  # necessary?
                            sweep_config["job"],
                            "--resource",
                            resource,
                        ],  # entry_point,
                        None,  # version,
                        None,  # resource_args,
                        None,  # launch_config,
                        None,  # run_id,
                        None,  # repository
                        user,  # author
                    )
                ),
            }
        )

        sweep_id, warnings = api.upsert_sweep(
            sweep_config,
            project=proj,
            entity=user,
            obj_id=None,
            launch_scheduler=_launch_scheduler_spec,
        )

        assert len(warnings) == 0
        assert sweep_id

        sweep_state = api.get_sweep_state(sweep_id, user, proj)

        assert sweep_state == "PENDING"

        public_api = PublicApi()
        sweep = public_api.sweep(f"{user}/{proj}/{sweep_id}")

        assert sweep.config == sweep_config

        res = api.pop_from_run_queue(queue, user, proj)

        if resource is None:
            # TODO(gst): Once the queue has a DRC's, should be DRC.resource
            assert not res
        else:
            assert res
            assert res["runSpec"]
            assert res["runSpec"]["resource"] == resource


@pytest.mark.parametrize("max_schedulers", [None, 0, -1, 2.0, "2"])
def test_launch_agent_scheduler(
    monkeypatch, user, wandb_init, test_settings, max_schedulers
):
    proj = "123"
    queue = "queue"
    settings = test_settings({"project": proj})
    run = wandb_init(settings=settings)

    job_artifact = run._log_job_artifact_with_image("docker_image", args=[])
    job_name = job_artifact.wait().name

    api = wandb.sdk.internal.internal_api.Api()
    api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

    sweep_config = {
        "job": job_name,
        "method": "bayes",
        "metric": {
            "name": "loss_metric",
            "goal": "minimize",
        },
        "parameters": {
            "epochs": {"value": 1},
            "increment": {"values": [0.1, 0.2, 0.3]},
        },
    }

    # Launch job spec for the Scheduler
    _launch_scheduler_spec = json.dumps(
        {
            "queue": queue,
            "run_spec": json.dumps(
                construct_launch_spec(
                    Scheduler.PLACEHOLDER_URI,  # uri
                    None,  # job
                    api,
                    "Scheduler.WANDB_SWEEP_ID",  # name,
                    proj,
                    user,
                    None,  # docker_image,
                    "local-process",  # resource,
                    [
                        "wandb",
                        "scheduler",
                        "WANDB_SWEEP_ID",
                        "--queue",
                        queue,
                        "--project",
                        proj,
                        "--job",  # necessary?
                        job_name,
                    ],  # entry_point,
                    None,  # version,
                    None,  # resource_args,
                    None,  # launch_config,
                    None,  # run_id,
                    None,  # repository
                    user,  # author
                )
            ),
        }
    )

    sweep_id, warnings = api.upsert_sweep(
        sweep_config,
        project=proj,
        entity=user,
        obj_id=None,
        launch_scheduler=_launch_scheduler_spec,
    )

    assert len(warnings) == 0
    assert sweep_id

    def _check_job(_, job):
        print(job)
        return

    def _raise(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        LaunchAgent,
        "run_job",
        _check_job,
    )

    api.ack_run_queue_item = _raise

    launch_agent = LaunchAgent(
        api=api,
        config={
            "entity": user,
            "project": proj,
            "queues": [queue],
            "max_schedulers": max_schedulers,
        },
    )

    if max_schedulers is None:
        assert launch_agent._max_schedulers == 1
    elif max_schedulers is -1:
        assert launch_agent._max_schedulers == float("inf")
    else:
        assert launch_agent._max_schedulers == int(max_schedulers)
