import json

import pytest
import wandb
from wandb.apis.public import Api as PublicApi
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
    docker_image = "testing321"

    with relay_server():
        run = wandb_init(settings=settings)
        # log fake job to use in scheduler
        job_artifact = run._log_job_artifact_with_image(docker_image, args=[])
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
                        "placeholder-uri-scheduler",  # uri
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
                            job_name,
                            "--resource",
                            resource,
                            # TODO(hupo): Add num-workers as option in launch config
                            # "--num_workers",
                            # launch_config.get("scheduler", {}).get("num_workers", 1),
                        ],  # entry_point,
                        None,  # version,
                        None,  # parameters,
                        None,  # resource_args,
                        None,  # launch_config,
                        None,  # cuda,
                        None,  # run_id,
                        None,  # repository
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

        run.finish()
