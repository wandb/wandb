import hashlib
from unittest.mock import MagicMock

from wandb.sdk.launch.builder import build


def test_get_env_vars_dict(mocker):
    _setup(mocker)

    resp = build.get_env_vars_dict(mocker.launch_project, mocker.api)

    assert resp == {
        "WANDB_API_KEY": "test-api-key",
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


def test_get_env_vars_dict_api_key_override(mocker):
    _setup(mocker)
    mocker.launch_project.launch_spec = {"_wandb_api_key": "override-api-key"}

    resp = build.get_env_vars_dict(mocker.launch_project, mocker.api)

    assert resp == {
        "WANDB_API_KEY": "override-api-key",
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
    }


def test_image_tag_from_dockerfile_and_source(mocker):
    _setup(mocker)
    source_string = "test-docker-image"
    mocker.launch_project.get_image_source_string = lambda: source_string
    resp = build.image_tag_from_dockerfile_and_source(mocker.launch_project, "")

    tag = hashlib.sha256(source_string.encode("utf-8")).hexdigest()[:8]

    assert resp == tag


def _setup(mocker):
    launch_project = MagicMock()
    launch_project.target_project = "test-project"
    launch_project.target_entity = "test-entity"
    launch_project.run_id = "test-run-id"
    launch_project.docker_image = "test-docker-image"
    launch_project.name = "test-name"
    launch_project.launch_spec = {"author": "test-author"}
    launch_project.override_config = {}
    launch_project.override_args = []
    launch_project.override_artifacts = {}

    mocker.launch_project = launch_project

    api = MagicMock()
    api.settings = lambda x: x
    api.api_key = "test-api-key"
    mocker.api = api

    mocker.patch("json.dumps", lambda x: "test-wandb-artifacts")
