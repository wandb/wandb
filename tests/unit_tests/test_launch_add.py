import json
import os

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
    queue = "queue-21"
    api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

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
        print(relay.context.raw_data)

    run.finish()  # weird file sync error if run ends too early

    assert result.exit_code == 0
    assert "'uri': None" in str(result.output)
    assert "'job': 'oops'" not in str(result.output)


def test_launch_build_with_config(relay_server, runner, user):
    # create a project
    proj = "test_project_919"
    os.environ["WANDB_PROJECT"] = proj
    run = wandb.init(project=proj)
    # create a queue in the project
    api = InternalApi()
    queue = "queue-23"

    api.create_run_queue(entity=user, project=proj, queue_name=queue, access="USER")

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

    run.finish()  # weird file sync error if run ends too early

    assert result.exit_code == 0
    assert "'uri': None" in str(result.output)
    assert "'job': 'oops'" not in str(result.output)
