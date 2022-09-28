import time

import wandb
from wandb.sdk.launch.launch_add import launch_add


def test_launch_add_default(relay_server, user):
    proj = "test_project"
    args = {
        "uri": "https://wandb.ai/lavanyashukla/basic-intro/runs/3dibi5mk",
        "project": proj,
        "entity": user,
        "queue": "default",
    }

    run = wandb.init(project=proj)
    time.sleep(1)

    with relay_server() as relay:
        queued_run = launch_add(**args)

    assert queued_run.id
    assert queued_run.state == "pending"
    assert queued_run.entity == args["entity"]
    assert queued_run.project == args["project"]
    assert queued_run.queue_id == args["queue"]

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        # below should fail for non-existent default queue,
        # then fallback to legacy method
        if q and "pushToRunQueueByName" in str(q):
            assert comm["response"]["data"]["pushToRunQueueByName"] is None
        elif q and "pushToRunQueue" in str(q):
            assert comm["response"]["data"]["pushToRunQueue"] is not None

    run.finish()


def test_push_to_runqueue_exists(relay_server, user):
    proj = "test_project"
    queue = "existing-queue"
    args = {
        "uri": "https://wandb.ai/lavanyashukla/basic-intro/runs/3dibi5mk",
        "project": proj,
        "entity": user,
        "queue": queue,
    }

    run = wandb.init(project=proj)
    time.sleep(1)

    api = wandb.sdk.internal.internal_api.Api()

    with relay_server() as relay:
        api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

        result = api.push_to_run_queue(queue, args)

        assert result["runQueueItemId"]

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        if q and "pushToRunQueueByName" in str(q):
            assert comm["response"]["data"] is not None
        elif q and "pushToRunQueue" in str(q):
            raise Exception("should not be falling back to legacy here")

    run.finish()


def test_push_to_default_runqueue_notexist(relay_server, user):
    api = wandb.sdk.internal.internal_api.Api()
    proj = "test_project"
    launch_spec = {
        "uri": "https://wandb.ai/lavanyashukla/basic-intro/runs/3dibi5mk",
        "entity": user,
        "project": proj,
    }
    run = wandb.init(project=proj)
    time.sleep(1)

    with relay_server():
        res = api.push_to_run_queue("nonexistent-queue", launch_spec)

        assert not res

    run.finish()
