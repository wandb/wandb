import pytest

import wandb
from wandb.cli import cli
from wandb.sdk.launch.launch_add import launch_add


def test_launch_add_default(wandb_init, relay_server, user):
    args = {
        "uri": "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "project": "test_project",
        "entity": user,
        "queue": "default",
    }

    with relay_server() as relay:
        run = wandb_init()
        result = launch_add(**args)
        run.finish()

    assert result.exit_code == 0

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        if q and "pushToRunQueueByName" in str(q):
            assert "xxx" in str(q)

        print(q, end="")
        print("variables", comm["request"]["variables"])
        print("response", comm["response"]["data"])
        print("\n")


def test_push_to_runqueue(wandb_init, relay_server, user):
    args = {
        "uri": "https://wandb.ai/mock_server_entity/test_project/runs/run",
        "project": "test_project",
        "entity": user,
        "queue": "default",
    }
    api = wandb.sdk.internal.internal_api.Api()

    with relay_server() as relay:
        run = wandb_init()
        result = api.push_to_run_queue("default", args)
        run.finish()

    assert result["runQueueItemId"]

    for comm in relay.context.raw_data:
        q = comm["request"].get("query")
        if q and "pushToRunQueueByName" in str(q):
            assert "xxx" in str(q)

        print(q, end="")
        print("variables", comm["request"]["variables"])
        print("response", comm["response"]["data"])
        print("\n")


def test_push_to_default_runqueue_notexist(wandb_init, relay_server, user):
    api = wandb.sdk.internal.internal_api.Api()
    launch_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
    }
    api.push_to_run_queue("default", launch_spec)


def test_push_to_runqueue_notfound(wandb_init, relay_server, user):
    api = wandb.sdk.internal.internal_api.Api()
    launch_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
    }
    api.push_to_run_queue("not-found", launch_spec)

    # assert "Unable to push to run queue not-found. Queue not found" in err
