import pytest
import wandb
from wandb.errors import LaunchError
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.launch.launch import run


def test_launch_repository(
    relay_server, runner, user, monkeypatch, wandb_init, test_settings
):
    queue = "default"
    proj = "test1"
    uri = "https://github.com/wandb/examples.git"
    entry_point = ["python", "/examples/examples/launch/launch-quickstart/train.py"]
    settings = test_settings({"project": proj})
    api = InternalApi()

    with relay_server():
        wandb_init(settings=settings).finish()
        api.create_run_queue(
            entity=user, project=proj, queue_name=queue, access="PROJECT"
        )

        with pytest.raises(LaunchError) as e_info:
            run(
                api,
                uri=uri,
                entity=user,
                project=proj,
                entry_point=entry_point,
                repository="testing123",
            )

        assert "Failed to push image to repository" in str(e_info)


def test_launch_incorrect_backend(
    relay_server, runner, user, monkeypatch, wandb_init, test_settings
):
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

    with relay_server():
        r = wandb_init(settings=settings)

        with pytest.raises(LaunchError) as e_info:
            run(
                api,
                uri=uri,
                entity=user,
                project=proj,
                entry_point=entry_point,
                resource="testing123",
            )

        assert "Resource name not among available resources" in str(e_info)
        r.finish()
