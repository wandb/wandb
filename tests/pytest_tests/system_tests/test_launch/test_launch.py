from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.errors import CommError
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch._launch import _launch
from wandb.sdk.launch.errors import LaunchError


class MockBuilder:
    def __init__(self, *args, **kwargs):
        pass

    async def verify(self):
        pass

    async def build_image(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_launch_incorrect_backend(
    runner, user, monkeypatch, wandb_init, test_settings
):
    proj = "test1"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": proj})
    api = InternalApi()

    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "LaunchProject",
        lambda *args, **kwargs: MagicMock(),
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
        lambda *args, **kawrgs: None,
    )
    (
        monkeypatch.setattr(
            "wandb.sdk.launch.loader.registry_from_config", lambda *args, **kawrgs: None
        ),
    )

    monkeypatch.setattr(
        "wandb.sdk.launch.loader.builder_from_config",
        lambda *args, **kawrgs: MockBuilder(),
    )
    r = wandb_init(settings=settings)
    r.finish()
    with pytest.raises(
        LaunchError,
        match="Could not create runner from config. Invalid runner name: testing123",
    ):
        await _launch(
            api,
            docker_image="testimage",
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
        assert run2.id == "test"


def test_launch_get_project_queue_error(user):
    proj = "projectq32e"
    api = InternalApi()
    with pytest.raises(
        CommError,
        match=f"Error fetching run queues for {user}/{proj} check that you have access to this entity and project",
    ):
        api.get_project_run_queues(user, proj)


def test_launch_wandb_init_launch_envs(
    relay_server, runner, user, wandb_init, test_settings
):
    queue = "test-queue-name"
    with runner.isolated_filesystem(), mock.patch.dict(
        "os.environ",
        {
            "WANDB_LAUNCH_QUEUE_NAME": queue,
            "WANDB_LAUNCH_QUEUE_ENTITY": user,
            "WANDB_LAUNCH_TRACE_ID": "test123",
        },
    ):
        with relay_server() as relay:
            run = wandb_init()
            run.log({"test": 1})
            run.finish()

        config = relay.context.config[run.id]

        assert config["_wandb"]["value"]["launch_trace_id"] == "test123"
        assert config["_wandb"]["value"]["launch_queue_entity"] == user
        assert config["_wandb"]["value"]["launch_queue_name"] == queue
