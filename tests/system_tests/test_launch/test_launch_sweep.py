import json

import wandb
from wandb.apis.public import Api as PublicApi
from wandb.cli import cli
from wandb.sdk.launch.sweeps.scheduler import Scheduler
from wandb.sdk.launch.utils import LAUNCH_DEFAULT_PROJECT, construct_launch_spec


def test_sweeps_on_launch(
    use_local_wandb_backend,
    user,
    monkeypatch,
):
    _ = use_local_wandb_backend
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
        lambda *_: None,
    )

    proj = "test_project2"
    queue = "existing-queue"

    with wandb.init(settings=wandb.Settings(project=proj)):
        pass

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
                        sweep_config["job"],
                        "--resource",
                        "local-process",
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
    assert res
    assert res["runSpec"]
    assert res["runSpec"]["resource"] == "local-process"


def test_sweep_scheduler_job_with_queue(runner, user, mocker):
    # Can't download artifacts in tests, so patch this
    mocker.patch("wandb.sdk.launch.sweeps.utils.check_job_exists", return_value=True)
    queue = "queue"
    settings = wandb.Settings(project=LAUNCH_DEFAULT_PROJECT)
    run = wandb.init(settings=settings)

    job_artifact = run._log_job_artifact_with_image("docker_image", args=[])
    job_name = job_artifact.wait().name

    api = wandb.sdk.internal.internal_api.Api()
    res = api.create_default_resource_config(
        user,
        "local-container",
        json.dumps({"resource_args": {"local-container": {"e": "{{var}}"}}}),
        {"var": {"schema": {"type": "string", "enum": ["1", "2"]}}},
    )
    id = res.get("defaultResourceConfigID")
    api.create_run_queue(
        entity=user,
        project=LAUNCH_DEFAULT_PROJECT,
        queue_name=queue,
        access="USER",
        config_id=id,
    )
    cli._get_cling_api(reset=True)
    with runner.isolated_filesystem():
        with open("config.json", "w") as f:
            json.dump(
                {
                    "queue": queue,
                    "resource": "local-container",
                    "job": f"{user}/{LAUNCH_DEFAULT_PROJECT}/{job_name}",
                    "scheduler": {
                        "job": f"{user}/{LAUNCH_DEFAULT_PROJECT}/{job_name}",
                        "resource": "local-container",
                        "template_variables": {"var": "1"},
                    },
                },
                f,
            )
        sweep_config = {
            "name": "My Sweep",
            "method": "grid",
            "parameters": {"parameter1": {"values": [1, 2, 3]}},
        }
        wandb.sweep(sweep_config)
        res = runner.invoke(
            cli.launch_sweep,
            ["config.json", "--queue", queue],
        )

        rqi = api.pop_from_run_queue(
            queue,
            user,
            LAUNCH_DEFAULT_PROJECT,
        )
        assert (
            rqi.get("runSpec").get("resource_args").get("local-container").get("e")
            == "1"
        )
        assert res.exit_code == 0
        assert queue in res.output
