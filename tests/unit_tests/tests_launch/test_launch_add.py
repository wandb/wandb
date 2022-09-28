import os
import time

import pytest
import wandb
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch_add import launch_add


def test_launch_delete_queued_run(relay_server, runner, user, monkeypatch):
    queue = "default"
    proj = "test"
    uri = "https://github.com/gtarpenning/wandb-launch-test"

    api = InternalApi()
    os.environ["WANDB_PROJECT"] = proj  # required for artifact query

    # create project
    run = wandb.init(project=proj)
    time.sleep(1)
    run.finish()

    with relay_server():
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        queued_run = launch_add(
            uri=uri,
            entity=user,
            project=proj,
            queue_name=queue,
        )

        assert queued_run.state == "pending"

        queued_run.delete()
