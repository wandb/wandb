"""Tests for the BuildContextManager class in the builder module."""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch.builder.context_manager import BuildContextManager


@pytest.fixture
def mock_git_project(mocker, tmp_path):
    mock_project = MagicMock()
    mock_project.project_dir = tmp_path
    mock_project.python_version = "3.8"
    mock_project.job_dockerfile = None
    mock_project.job_build_context = None
    mock_project.override_dockerfile = None
    mock_project.override_entrypoint.command = ["python", "entrypoint.py"]
    mock_project.override_entrypoint.name = "entrypoint.py"
    mock_project.get_image_source_string.return_value = "image_source"
    mock_project.accelerator_base_image = None
    mock_project.get_job_entry_point.return_value = mock_project.override_entrypoint
    mocker.patch(
        "wandb.sdk.launch.builder.context_manager.get_docker_user",
        return_value=("docker_user", 1000),
    )
    mocker.patch(
        "wandb.sdk.launch.builder.build.docker.is_buildx_installed",
        return_value=False,
    )
    return mock_project


def test_create_build_context_wandb_dockerfile(mock_git_project):
    """Test that a Dockerfile is generated when no Dockerfile is specified.

    The generated Dockerfile should include the Python version, the job's
    requirements, and the entrypoint.
    """
    (mock_git_project.project_dir / "requirements.txt").write_text("wandb")
    (mock_git_project.project_dir / "entrypoint.py").write_text("import wandb")

    build_context_manager = BuildContextManager(mock_git_project)
    path, image_tag = build_context_manager.create_build_context("docker")

    path = pathlib.Path(path)
    dockerfile = (path / "Dockerfile.wandb").read_text()
    assert "FROM python:3.8" in dockerfile
    assert "uv pip install -r requirements.txt" in dockerfile
    assert (path / "src" / "entrypoint.py").exists()
    assert (path / "src" / "requirements.txt").exists()
    assert (
        image_tag == "62143254"
    )  # This is the hash of the Dockerfile + image_source_string.


def test_create_build_context_override_dockerfile(mock_git_project):
    """Test that a custom Dockerfile is used when specified."""
    (mock_git_project.project_dir / "Dockerfile").write_text("FROM custom:3.8")
    mock_git_project.override_dockerfile = "Dockerfile"

    build_context_manager = BuildContextManager(mock_git_project)
    path, image_tag = build_context_manager.create_build_context("docker")

    path = pathlib.Path(path)
    dockerfile = (path / "Dockerfile.wandb").read_text()
    assert dockerfile.strip() == "FROM custom:3.8"
    assert (
        image_tag == "6390dc92"
    )  # This is the hash of the Dockerfile + image_source_string.


def test_create_build_context_dockerfile_dot_wandb(mock_git_project):
    """Tests that a Dockerfile.wandb is used when found adjacent to the entrypoint."""
    mock_git_project.override_entrypoint.name = "subdir/entrypoint.py"
    mock_git_project.override_entrypoint.command = ["python", "subdir/entrypoint.py"]
    subdir = mock_git_project.project_dir / "subdir"
    subdir.mkdir()
    (subdir / "Dockerfile.wandb").write_text("FROM custom:3.8 # dockerfile.wandb")
    (subdir / "entrypoint.py").write_text("import wandb")

    build_context_manager = BuildContextManager(mock_git_project)
    path, image_tag = build_context_manager.create_build_context("docker")

    path = pathlib.Path(path)
    dockerfile = (path / "Dockerfile.wandb").read_text()
    assert dockerfile.strip() == "FROM custom:3.8 # dockerfile.wandb"
    assert (
        image_tag == "74fc4318"
    )  # This is the hash of the Dockerfile + image_source_string.


def test_create_build_context_job_dockerfile(mock_git_project):
    """Test that a custom Dockerfile is used when specified in the job config."""
    (mock_git_project.project_dir / "Dockerfile").write_text("FROM custom:3.8")
    mock_git_project.job_dockerfile = "Dockerfile"

    build_context_manager = BuildContextManager(mock_git_project)
    path, image_tag = build_context_manager.create_build_context("docker")

    path = pathlib.Path(path)
    dockerfile = (path / "Dockerfile.wandb").read_text()
    assert dockerfile.strip() == "FROM custom:3.8"
    assert (
        image_tag == "6390dc92"
    )  # This is the hash of the Dockerfile + image_source_string.


def test_create_build_context_job_build_context(mock_git_project):
    """Test that a custom build context is used when specified in the job config."""
    subdir = mock_git_project.project_dir / "subdir"
    subdir.mkdir()
    (subdir / "Dockerfile").write_text("FROM custom:3.8")
    mock_git_project.job_build_context = "subdir"
    mock_git_project.job_dockerfile = "Dockerfile"

    build_context_manager = BuildContextManager(mock_git_project)
    path, image_tag = build_context_manager.create_build_context("docker")

    path = pathlib.Path(path)
    dockerfile = (path / "Dockerfile.wandb").read_text()
    assert dockerfile.strip() == "FROM custom:3.8"
    assert (
        image_tag == "6390dc92"
    )  # This is the hash of the Dockerfile + image_source_string.


def test_create_build_context_buildx_enabled(mocker, mock_git_project):
    """Test that a Dockerfile is generated when buildx is enabled."""
    (mock_git_project.project_dir / "requirements.txt").write_text("wandb")
    (mock_git_project.project_dir / "entrypoint.py").write_text("import wandb")
    mocker.patch(
        "wandb.sdk.launch.builder.build.docker.is_buildx_installed",
        return_value=True,
    )

    build_context_manager = BuildContextManager(mock_git_project)
    path, image_tag = build_context_manager.create_build_context("docker")

    path = pathlib.Path(path)
    dockerfile = (path / "Dockerfile.wandb").read_text()
    assert "FROM python:3.8" in dockerfile
    assert "uv pip install -r requirements.txt" in dockerfile
    assert "RUN WANDB_DISABLE_CACHE=true" not in dockerfile
    assert (path / "src" / "entrypoint.py").exists()
    assert (path / "src" / "requirements.txt").exists()
    assert (
        image_tag == "f17a9120"
    )  # This is the hash of the Dockerfile + image_source_string.
