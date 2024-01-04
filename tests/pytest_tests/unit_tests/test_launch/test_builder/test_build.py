import hashlib
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.builder import build
from wandb.sdk.launch.builder.build import registry_from_uri
from wandb.sdk.launch.errors import LaunchError


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://test.azurecr.io/my-repo", "azure_container_registry"),
        (
            "us-central1-docker.pkg.dev/my-gcp-project/my-repo/image-name",
            "google_artifact_registry",
        ),
        (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-repo",
            "elastic_container_registry",
        ),
        ("unsupported_format.com/my_repo", None),
    ],
)
def test_registry_from_uri(url, expected, mocker):
    mocker.patch(
        "wandb.sdk.launch.registry.azure_container_registry.AzureContainerRegistry",
        MagicMock(return_value="azure_container_registry"),
    )
    mocker.patch(
        "wandb.sdk.launch.registry.google_artifact_registry.GoogleArtifactRegistry",
        MagicMock(return_value="google_artifact_registry"),
    )
    mocker.patch(
        "wandb.sdk.launch.registry.elastic_container_registry.ElasticContainerRegistry",
        MagicMock(return_value="elastic_container_registry"),
    )

    if expected is None:
        with pytest.raises(LaunchError):
            registry_from_uri(url)
    else:
        assert registry_from_uri(url) == expected


def test_get_env_vars_dict(mocker):
    _setup(mocker)

    resp = build.get_env_vars_dict(mocker.launch_project, mocker.api, 512)

    assert resp == {
        "WANDB_API_KEY": "test-api-key",
        "WANDB_ARTIFACTS": "test-wandb-artifacts",
        "WANDB_BASE_URL": "base_url",
        "WANDB_CONFIG": "test-wandb-artifacts",
        "WANDB_DOCKER": "test-docker-image",
        "WANDB_ENTITY": "test-entity",
        "WANDB_LAUNCH": "True",
        "WANDB_LAUNCH_QUEUE_NAME": "test-queue-name",
        "WANDB_LAUNCH_QUEUE_ENTITY": "test-queue-entity",
        "WANDB_LAUNCH_TRACE_ID": "test-run-queue-item-id",
        "WANDB_NAME": "test-name",
        "WANDB_PROJECT": "test-project",
        "WANDB_RUN_ID": "test-run-id",
        "WANDB_USERNAME": "test-author",
        "WANDB_SWEEP_ID": "test-sweep-id",
    }


def test_get_env_vars_dict_api_key_override(mocker):
    _setup(mocker)
    mocker.launch_project.launch_spec = {"_wandb_api_key": "override-api-key"}

    resp = build.get_env_vars_dict(mocker.launch_project, mocker.api, 10)

    assert resp == {
        "WANDB_API_KEY": "override-api-key",
        "WANDB_ARTIFACTS": "test-wandb-artifacts",
        "WANDB_BASE_URL": "base_url",
        "WANDB_CONFIG_0": "test-wandb",
        "WANDB_CONFIG_1": "-artifacts",
        "WANDB_DOCKER": "test-docker-image",
        "WANDB_ENTITY": "test-entity",
        "WANDB_LAUNCH": "True",
        "WANDB_LAUNCH_QUEUE_NAME": "test-queue-name",
        "WANDB_LAUNCH_QUEUE_ENTITY": "test-queue-entity",
        "WANDB_LAUNCH_TRACE_ID": "test-run-queue-item-id",
        "WANDB_NAME": "test-name",
        "WANDB_PROJECT": "test-project",
        "WANDB_RUN_ID": "test-run-id",
        "WANDB_SWEEP_ID": "test-sweep-id",
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
    launch_project.sweep_id = "test-sweep-id"
    launch_project.docker_image = "test-docker-image"
    launch_project.name = "test-name"
    launch_project.launch_spec = {"author": "test-author"}
    launch_project.queue_name = "test-queue-name"
    launch_project.queue_entity = "test-queue-entity"
    launch_project.run_queue_item_id = "test-run-queue-item-id"
    launch_project.override_config = {}
    launch_project.override_args = []
    launch_project.override_artifacts = {}

    mocker.launch_project = launch_project

    api = MagicMock()
    api.settings = lambda x: x
    api.api_key = "test-api-key"
    mocker.api = api

    mocker.patch("json.dumps", lambda x: "test-wandb-artifacts")
