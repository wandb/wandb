from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.errors import CommError
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch import run
from wandb.sdk.launch.utils import LaunchError


def test_launch_incorrect_backend(runner, user, monkeypatch, wandb_init, test_settings):
    proj = "test1"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": proj})
    api = InternalApi()

    monkeypatch.setattr(
        "wandb.sdk.launch.launch.fetch_and_validate_project",
        lambda _1, _2: "something",
    )

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "validate_docker_installation",
        lambda: None,
    )

    monkeypatch.setattr(
        "wandb.docker",
        lambda: None,
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.loader.environment_from_config",
        lambda *args, **kawrgs: MagicMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.loader.registry_from_config",
        lambda *args, **kawrgs: MagicMock(),
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.loader.builder_from_config",
        lambda *args, **kawrgs: MagicMock(),
    )
    r = wandb_init(settings=settings)
    r.finish()
    with pytest.raises(
        LaunchError,
        match="Could not create runner from config. Invalid runner name: testing123",
    ):
        run(
            api,
            uri=uri,
            entity=user,
            project=proj,
            entry_point=entry_point,
            resource="testing123",
        )


def test_launch_multi_run(relay_server, runner, user, wandb_init, test_settings):
    with runner.isolated_filesystem(), mock.patch.dict(
        "os.environ", {"WANDB_RUN_ID": "test", "WANDB_LAUNCH": "true"}
    ):
        run1 = wandb_init()
        run1.finish()

        run2 = wandb_init()
        run2.finish()

        assert run1.id == "test"
        assert run2.id != "test"


def test_launch_multi_run_context(
    relay_server, runner, user, wandb_init, test_settings
):
    with runner.isolated_filesystem(), mock.patch.dict(
        "os.environ", {"WANDB_RUN_ID": "test", "WANDB_LAUNCH": "true"}
    ):
        with wandb_init() as run1:
            run1.log({"test": 1})

        with wandb_init() as run2:
            run2.log({"test": 2})

        assert run1.id == "test"
        assert run2.id != "test"


def test_launch_get_project_queue_error(user):
    proj = "projectq32e"
    api = InternalApi()
    with pytest.raises(
        CommError,
        match=f"Error fetching run queues for {user}/{proj} check that you have access to this entity and project",
    ):
        api.get_project_run_queues(user, proj)
