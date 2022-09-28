import json
import os
import time

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add

from wandb.wandb_run import Run


@pytest.mark.timeout(300)  # builds a container
def test_launch_build_push_job(relay_server, runner, user, monkeypatch):
    RELEASE_IMAGE = "THIS IS AN IMAGE TAG"
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

        return RELEASE_IMAGE

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "make_image_uri",
        lambda b, l, r, e, d: patched_make_image_uri(b, l, r, e, d),
    )

    with relay_server() as relay:
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

        # queued_run.delete()

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        if q:
            wandb.termlog(q)
            print("variables", comm["request"]["variables"])
            print("response", comm["response"]["data"])
            print("\n")

    # assert result.exit_code == 0
    # assert "'uri': None" in str(result.output)
    # assert "'job': 'oops'" not in str(result.output)
