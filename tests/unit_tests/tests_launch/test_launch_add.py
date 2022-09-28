import os
import time

import pytest
import wandb
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add


@pytest.mark.timeout(300)  # builds a container
def test_launch_build_push_job(relay_server, runner, user, monkeypatch):
    release_image = "THISISANIMAGETAG"
    queue = "test_queue"
    proj = "test"
    uri = "https://github.com/gtarpenning/wandb-launch-test"

    api = InternalApi()
    os.environ["WANDB_PROJECT"] = proj  # required for artifact query

    # create project
    run = wandb.init(project=proj)
    time.sleep(1)
    run.finish()

    def patched_make_image_uri(
        builder,
        launch_project,
        repository,
        entry_point,
        docker_args,
    ):
        assert uri == launch_project.uri
        assert entry_point
        assert docker_args

        return release_image

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "make_image_uri",
        lambda b, l, r, e, d: patched_make_image_uri(b, l, r, e, d),
    )

    with relay_server():
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            queue=queue,
            build=True,
            job="DELETE ME",
        )

        assert queued_run.state == "pending"
        assert queued_run.entity == user
        assert queued_run.project == proj
        assert queued_run.container_job  # requires a correctly picked up job

        rqi = api.pop_from_run_queue(queue, user, proj)

        assert rqi["runSpec"]["uri"] is None
        assert rqi["runSpec"]["job"] == f"job-{release_image}:v0"
