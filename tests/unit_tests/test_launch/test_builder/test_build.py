from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

import pytest
from wandb.sdk.artifacts.artifact import Artifact
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.builder import build
from wandb.sdk.launch.builder.abstract import registry_from_uri
from wandb.sdk.launch.builder.context_manager import get_requirements_section
from wandb.sdk.launch.builder.templates.dockerfile import PIP_TEMPLATE
from wandb.sdk.launch.create_job import _configure_job_builder_for_partial


def _read_wandb_job_json_from_artifact(artifact: Artifact) -> dict:
    """Helper function to read wandb-job.json content from an artifact."""
    job_json_path = None
    for entry_path, entry in artifact.manifest.entries.items():
        if entry_path.endswith("wandb-job.json"):
            job_json_path = entry.local_path
            break

    assert job_json_path is not None, "wandb-job.json not found in artifact"

    with open(job_json_path) as f:
        return json.load(f)


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
    mocker, mock_launch_project, tmp_path, no_buildx
):
    """Test that we use the user provided requirements.txt."""
    mocker.termwarn = MagicMock()
    mocker.patch("wandb.termwarn", mocker.termwarn)
    mock_launch_project.project_dir = tmp_path
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "requirements.txt").write_text("")
    assert get_requirements_section(
        mock_launch_project, tmp_path, "docker"
    ) == PIP_TEMPLATE.format(
        buildx_optional_prefix="RUN WANDB_DISABLE_CACHE=true",
        requirements_files="src/requirements.txt",
        pip_install="pip install uv && uv pip install -r requirements.txt",
    )
    warn_msgs = mocker.termwarn.call_args.args
    assert any(
        ["wandb is not present in requirements.txt." in msg for msg in warn_msgs]
    )

    # No warning if wandb is in requirements
    mocker.termwarn.reset_mock()
    (tmp_path / "src" / "requirements.txt").write_text("wandb")
    get_requirements_section(mock_launch_project, tmp_path, "docker")
    warn_msgs = mocker.termwarn.call_args.args
    assert not any(
        ["wandb is not present in requirements.txt." in msg for msg in warn_msgs]
    )


def test_get_requirements_section_frozen_requirements(
    mocker, mock_launch_project, tmp_path, no_buildx
):
    """Test that we use frozen requirements.txt if nothing else is provided."""
    mocker.termwarn = MagicMock()
    mocker.patch("wandb.termwarn", mocker.termwarn)
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
    warn_msgs = mocker.termwarn.call_args.args
    assert any(
        ["wandb is not present in requirements.frozen.txt." in msg for msg in warn_msgs]
    )

    # No warning if wandb is in requirements
    mocker.termwarn.reset_mock()
    (tmp_path / "src" / "requirements.frozen.txt").write_text("wandb")
    get_requirements_section(mock_launch_project, tmp_path, "docker")
    warn_msgs = mocker.termwarn.call_args.args
    assert not any(
        ["wandb is not present in requirements.frozen.txt." in msg for msg in warn_msgs]
    )


def test_get_requirements_section_pyproject(
    mocker, mock_launch_project, tmp_path, no_buildx
):
    """Test that we install deps from [project.dependencies] in pyprojec.toml.

    This should only happen if there is no requirements.txt in the directory.
    """
    mocker.termwarn = MagicMock()
    mocker.patch("wandb.termwarn", mocker.termwarn)
    mock_launch_project.project_dir = tmp_path
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pyproject.toml").write_text(
        "[project]\ndependencies = ['pandas==0.0.0']\n"
    )
    assert get_requirements_section(
        mock_launch_project, tmp_path, "docker"
    ) == PIP_TEMPLATE.format(
        buildx_optional_prefix="RUN WANDB_DISABLE_CACHE=true",
        requirements_files="src/requirements.txt",  # We convert into this format.
        pip_install="pip install uv && uv pip install -r requirements.txt",
    )
    warn_msgs = mocker.termwarn.call_args.args
    assert any(
        [
            "wandb is not present as a dependency in pyproject.toml." in msg
            for msg in warn_msgs
        ]
    )

    # No warning if wandb is in requirements
    mocker.termwarn.reset_mock()
    (tmp_path / "src" / "requirements.txt").unlink()
    (tmp_path / "src" / "pyproject.toml").write_text(
        "[project]\ndependencies = ['wandb==0.0.0', 'pandas==0.0.0']\n"
    )
    get_requirements_section(mock_launch_project, tmp_path, "docker")
    warn_msgs = mocker.termwarn.call_args.args
    assert not any(
        [
            "wandb is not present as a dependency in pyproject.toml." in msg
            for msg in warn_msgs
        ]
    )


def test_job_builder_includes_services_in_wandb_job_json(tmp_path):
    metadata = {
        "python": "3.9",
        "codePath": "main.py",
        "entrypoint": ["python", "main.py"],
        "docker": "my-image:latest",
    }
    (tmp_path / "wandb-metadata.json").write_text(json.dumps(metadata))
    (tmp_path / "requirements.txt").write_text("wandb")

    job_builder = _configure_job_builder_for_partial(str(tmp_path), job_source="image")
    job_builder._services = {"foobar": "always", "barfoo": "never"}

    artifact = job_builder.build(MagicMock())

    job_json = _read_wandb_job_json_from_artifact(artifact)
    assert "services" in job_json
    assert job_json["services"] == {"foobar": "always", "barfoo": "never"}


def test_job_builder_excludes_services_in_wandb_job_json(tmp_path):
    """Test that JobBuilder.build excludes services key when no services are set."""
    metadata = {
        "python": "3.9",
        "codePath": "main.py",
        "entrypoint": ["python", "main.py"],
        "docker": "my-image:latest",
    }
    (tmp_path / "wandb-metadata.json").write_text(json.dumps(metadata))
    (tmp_path / "requirements.txt").write_text("wandb")

    job_builder = _configure_job_builder_for_partial(str(tmp_path), job_source="image")
    job_builder._services = {}

    artifact = job_builder.build(MagicMock())

    assert artifact is not None
    job_json = _read_wandb_job_json_from_artifact(artifact)
    assert "services" not in job_json
