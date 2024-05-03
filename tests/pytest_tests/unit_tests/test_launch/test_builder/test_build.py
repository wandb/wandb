import hashlib
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.builder import build
from wandb.sdk.launch.builder.abstract import registry_from_uri
from wandb.sdk.launch.builder.context_manager import get_requirements_section
from wandb.sdk.launch.builder.templates.dockerfile import PIP_TEMPLATE


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
        ("unsupported_format.com/my_repo", "anon"),
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
    mocker.patch(
        "wandb.sdk.launch.builder.abstract.AnonynmousRegistry",
        MagicMock(return_value="anon"),
    )
    assert registry_from_uri(url) == expected


def test_image_tag_from_dockerfile_and_source(mocker):
    _setup(mocker)
    source_string = "test-docker-image"
    mocker.launch_project.get_image_source_string = lambda: source_string
    resp = build.image_tag_from_dockerfile_and_source(mocker.launch_project, "")

    tag = hashlib.sha256(source_string.encode("utf-8")).hexdigest()[:8]

    assert resp == tag


@pytest.fixture
def mock_launch_project(mocker):
    """Fixture for creating a mock LaunchProject."""
    launch_project = MagicMock(
        spec=LaunchProject,
        entry_point=EntryPoint("main.py", ["python", "main.py"]),
        deps_type="pip",
        docker_image="test-docker-image",
        name="test-name",
        launch_spec={"author": "test-author"},
        queue_name="test-queue-name",
        queue_entity="test-queue-entity",
        run_queue_item_id="test-run-queue-item-id",
        override_config={},
        override_args=[],
        override_artifacts={},
        python_version="3.9.11",
    )
    launch_project.get_job_entry_point = lambda: launch_project.entry_point
    return launch_project


def _setup(mocker):
    launch_project = MagicMock()
    launch_project.job = None
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
    launch_project.override_config = {
        "test-key": "test-value",
    }
    launch_project.override_files = {
        "test-path": "test-config",
    }
    launch_project.override_args = []
    launch_project.override_artifacts = {}

    mocker.launch_project = launch_project

    api = MagicMock()
    api.settings = lambda x: x
    api.api_key = "test-api-key"
    mocker.api = api


@pytest.fixture
def no_buildx(mocker):
    """Patches wandb.docker.is_buildx_installed to always return False."""
    mocker.patch(
        "wandb.sdk.launch.builder.build.docker.is_buildx_installed",
        lambda: False,
    )


def test_get_requirements_section_user_provided_requirements(
    mock_launch_project, tmp_path, no_buildx
):
    """Test that we use the user provided requirements.txt."""
    mock_launch_project.project_dir = tmp_path
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "requirements.txt").write_text("")
    assert get_requirements_section(
        mock_launch_project, tmp_path, "docker"
    ) == PIP_TEMPLATE.format(
        buildx_optional_prefix="RUN WANDB_DISABLE_CACHE=true",
        requirements_files="src/requirements.txt",
        pip_install="pip install -r requirements.txt",
    )


def test_get_requirements_section_frozen_requirements(
    mock_launch_project, tmp_path, no_buildx
):
    """Test that we use frozen requirements.txt if nothing else is provided."""
    mock_launch_project.project_dir = tmp_path
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "requirements.frozen.txt").write_text("")
    mock_launch_project.parse_existing_requirements = lambda: ""
    assert get_requirements_section(
        mock_launch_project, tmp_path, "docker"
    ) == PIP_TEMPLATE.format(
        buildx_optional_prefix="RUN WANDB_DISABLE_CACHE=true",
        requirements_files="src/requirements.frozen.txt _wandb_bootstrap.py",
        pip_install="python _wandb_bootstrap.py",
    )


def test_get_requirements_section_pyproject(mock_launch_project, tmp_path, no_buildx):
    """Test that we install deps from [project.dependencies] in pyprojec.toml.

    This should only happen if there is no requirements.txt in the directory.
    """
    mock_launch_project.project_dir = tmp_path
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pyproject.toml").write_text(
        "[project]\ndependencies = ['wandb==0.0.0', 'pandas==0.0.0']\n"
    )
    assert get_requirements_section(
        mock_launch_project, tmp_path, "docker"
    ) == PIP_TEMPLATE.format(
        buildx_optional_prefix="RUN WANDB_DISABLE_CACHE=true",
        requirements_files="src/requirements.txt",  # We convert into this format.
        pip_install="pip install -r requirements.txt",
    )
