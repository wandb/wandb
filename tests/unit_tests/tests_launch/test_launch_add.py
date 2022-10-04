import json
import os
import time

import pytest
import wandb
from wandb.apis.public import Api as PublicApi
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add


@pytest.mark.parametrize(
    "launch_config,override_config",
    [
        (
            {"build": {"type": "docker"}},
            {"docker": {"args": ["--container_arg", "9 rams"]}},
        ),
        ({}, {"cuda": False, "overrides": {"args": ["--runtime", "nvidia"]}}),
        (
            {"build": {"type": "docker"}},
            {"cuda": False, "overrides": {"args": ["--runtime", "nvidia"]}},
        ),
        ({"build": {"type": ""}}, {}),
    ],
)
def test_launch_build_push_job(
    relay_server, user, monkeypatch, runner, launch_config, override_config
):
    release_image = "THISISANIMAGETAG"
    queue = "test_queue"
    proj = "test"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]

    internal_api = InternalApi()
    public_api = PublicApi()
    os.environ["WANDB_PROJECT"] = proj  # required for artifact query

    # create project
    run = wandb.init(project=proj)
    time.sleep(1)

    def patched_validate_docker_installation():
        return None

    def patched_build_image_with_builder(
        builder,
        launch_project,
        repository,
        entry_point,
        docker_args,
    ):
        assert builder
        assert uri == launch_project.uri
        assert entry_point
        if override_config and override_config.get("docker"):
            assert docker_args == override_config.get("docker").get("args")

        return release_image

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: patched_validate_docker_installation(),
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "LAUNCH_CONFIG_FILE",
        "./config/wandb/launch-config.yaml",
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "build_image_with_builder",
        lambda *args, **kwargs: patched_build_image_with_builder(*args, **kwargs),
    )

    with relay_server(), runner.isolated_filesystem():
        os.makedirs(os.path.expanduser("./config/wandb"))
        with open(os.path.expanduser("./config/wandb/launch-config.yaml"), "w") as f:
            json.dump(launch_config, f)

        internal_api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            queue=queue,
            build=True,
            job="DELETE ME",
            entry_point=entry_point,
            config=override_config,
        )

        assert queued_run.state == "pending"
        assert queued_run.entity == user
        assert queued_run.project == proj
        assert queued_run.container_job is True

        rqi = internal_api.pop_from_run_queue(queue, user, proj)

        assert rqi["runSpec"]["uri"] is None
        assert rqi["runSpec"]["job"] != "DELETE ME"
        assert rqi["runSpec"]["job"].split("/")[-1] == f"job-{release_image}:v0"

        job = public_api.job(rqi["runSpec"]["job"])

        assert job._source_info["source"]["image"] == release_image

    run.finish()
