from unittest.mock import MagicMock, mock_open, patch

import wandb
from wandb.docker import DockerError
from wandb.sdk.launch._project_spec import (
    EntryPoint,
    create_project_from_spec,
    fetch_and_validate_project,
)
from wandb.sdk.launch.builder.build import generate_dockerfile, get_base_setup
from wandb.sdk.launch.utils import docker_image_exists

from .test_launch import (
    mocked_fetchable_git_repo,
    mocked_fetchable_git_repo_conda,
    mocked_fetchable_git_repo_nodeps,
)


def test_accelerator_base_setup(
    test_settings, live_mock_server, mocked_fetchable_git_repo
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "local-container",
        "resource_args": {
            "local-container": {
                "builder": {
                    "accelerator": {
                        "base_image": "nvidia/cuda:11.0-runtime",
                    }
                }
            }
        },
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    base_setup = get_base_setup(test_project, "3.7", "3")
    assert "FROM nvidia/cuda:11.0-runtime as base" in base_setup
    assert "python3-pip" in base_setup and "python3-setuptools" in base_setup


def test_run_accelerator_version(
    runner, live_mock_server, mocked_fetchable_git_repo, test_settings
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "local-container",
        "resource_args": {
            "local-container": {
                "builder": {
                    "accelerator": {
                        "base_image": "nvidia/cuda:11.0-runtime",
                    }
                }
            }
        },
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )
    assert "FROM nvidia/cuda:11.0-runtime as base" in dockerfile

    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "local",
        "resource_args": {},
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )
    assert "FROM python:" in dockerfile


def test_dockerfile_conda(
    test_settings, live_mock_server, mocked_fetchable_git_repo_conda, monkeypatch
):
    monkeypatch.setattr("wandb.docker.is_buildx_installed", lambda: True)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "local",
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)

    assert test_project.deps_type == "conda"

    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )
    assert "conda env create -f environment.yml" in dockerfile
    assert "FROM continuumio/miniconda3:latest as build" in dockerfile
    assert "RUN --mount=type=cache,mode=0777,target=/opt/conda/pkgs" in dockerfile


def test_dockerfile_nodeps(
    test_settings, live_mock_server, mocked_fetchable_git_repo_nodeps, monkeypatch
):
    monkeypatch.setattr("wandb.docker.is_buildx_installed", lambda: True)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "local",
    }

    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)

    assert test_project.deps_type is None

    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )
    assert "environment.yml" not in dockerfile
    assert "requirements.txt" not in dockerfile


def test_dockerfile_override(
    test_settings, live_mock_server, mocked_fetchable_git_repo_nodeps, monkeypatch
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "local",
    }

    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)

    assert test_project.deps_type is None

    dockerfile_contents = "test Dockerfile contents"
    with patch("builtins.open", mock_open(read_data=dockerfile_contents)) as mock_file:
        monkeypatch.setattr("os.path.exists", lambda _: True)
        dockerfile = generate_dockerfile(
            test_project,
            EntryPoint("main.py", ["python", "train.py"]),
            "local",
            "docker",
            "test/path/to/my/Dockerfile",
        )
    assert "test Dockerfile contents" in dockerfile
    assert "test/path/to/my/Dockerfile" in mock_file.call_args_list[0][0][0]


def test_docker_image_exists(
    test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):
    def raise_docker_error(args):
        raise DockerError(args, 1, b"", b"")

    monkeypatch.setattr(wandb.docker, "run", lambda args: raise_docker_error(args))
    assert docker_image_exists("test:image") == False
