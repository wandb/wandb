from unittest.mock import MagicMock

from wandb.sdk.launch.builder import build


def test_get_env_vars_dict(mocker):
    _setup(mocker)

    resp = build.get_env_vars_dict(mocker.launch_project, mocker.api)

    assert resp == {
        "WANDB_API_KEY": "test-api-key",
        "WANDB_ARGS": "",
        "WANDB_ARTIFACTS": "test-wandb-artifacts",
        "WANDB_BASE_URL": "base_url",
        "WANDB_CONFIG": "test-wandb-artifacts",
        "WANDB_DOCKER": "test-docker-image",
        "WANDB_ENTITY": "test-entity",
        "WANDB_ENTRYPOINT_COMMAND": "",
        "WANDB_LAUNCH": "True",
        "WANDB_NAME": "test-name",
        "WANDB_PROJECT": "test-project",
        "WANDB_RUN_ID": "test-run-id",
        "WANDB_USERNAME": "test-author",
    }


def _setup(mocker):
    launch_project = MagicMock()
    launch_project.target_project = "test-project"
    launch_project.target_entity = "test-entity"
    launch_project.run_id = "test-run-id"
    launch_project.docker_image = "test-docker-image"
    launch_project.name = "test-name"
    launch_project.launch_spec = {"author": "test-author"}
    launch_project.override_config = {}
    launch_project.override_artifacts = {}
    mocker.launch_project = launch_project

    api = MagicMock()
    api.settings = lambda x: x
    api.api_key = "test-api-key"
    mocker.api = api

    mocker.patch("json.dumps", lambda x: "test-wandb-artifacts")
