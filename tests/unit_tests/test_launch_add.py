import os
import json

import pytest
import wandb
from wandb.cli import cli
from wandb.sdk.internal.internal_api import Api as InternalApi


@pytest.fixture()
def launch_queue(api=None):
    """
    Create a fixture that creates a launch queue, required for
    all launch `--queue` tests

    TODO: How to pass the username into this function? randomly generated
       so it must be passed in...
    """
    pass


@pytest.mark.timeout(300)  # builds a container
def test_launch_build_push_job(relay_server, runner, user):
    # create a project
    proj = "test_project_917"
    os.environ["WANDB_PROJECT"] = proj
    run = wandb.init(project=proj)
    # create a queue in the project
    api = InternalApi()
    queue = "default"
    api.create_run_queue(entity=user, project=proj, queue_name=queue, access="PROJECT")

    args = [
        "https://github.com/gtarpenning/wandb-launch-test",
        f"--project={proj}",
        f"--entity={user}",
        "--job=oops",
        f"--queue={queue}",
        "--build",
    ]
    with relay_server() as relay:
        result = runner.invoke(cli.launch, args)
        for comm in relay.context.raw_data:
            print("\n\n", comm)

    run_queue = api.get_project_run_queues(entity=user, project=proj)
    _ = run_queue.pop()
    run_queue.clear()
    del run_queue

    run.finish()  # weird file sync error if run ends too early

    assert result.exit_code == 0
    assert "'uri': None" in str(result.output)
    assert "'job': 'oops'" not in str(result.output)


@pytest.mark.timeout(300)
def test_launch_build_with_config(relay_server, runner, user):
    # create a project
    proj = "test_project_919"
    os.environ["WANDB_PROJECT"] = proj
    run = wandb.init(project=proj)
    # create a queue in the project
    api = InternalApi()
    queue = "default"

    api.create_run_queue(entity=user, project=proj, queue_name=queue, access="PROJECT")

    config = {
        "cuda": False,
        "overrides": {"args": ["--epochs", "5"]},
    }

    args = [
        "https://github.com/gtarpenning/wandb-launch-test",
        f"--project={proj}",
        f"--entity={user}",
        "--job=oops",
        f"--queue={queue}",
        "--build",
        f"--config={json.dumps(config)}",
    ]
    with relay_server() as relay:
        result = runner.invoke(cli.launch, args)
        print(relay.context.raw_data)

        run_queue_item = api.pop_from_run_queue(
            queue_name=queue, entity=user, project=proj
        )

        assert f"'entity': '{user}'" in str(run_queue_item)
        assert run_queue_item["runSpec"]["overrides"] == {"args": {"epochs": "5"}}
        del run_queue_item

    run_queue = api.get_project_run_queues(entity=user, project=proj)
    run_queue.clear()
    del run_queue

    run.finish()  # weird file sync error if run ends too early

    assert result.exit_code == 0
    assert "'uri': None" in str(result.output)
    assert "'job': 'oops'" not in str(result.output)
