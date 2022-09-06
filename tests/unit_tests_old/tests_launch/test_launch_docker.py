import json
import os
import sys
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.errors import DockerError
from wandb.sdk.launch._project_spec import (
    EntryPoint,
    create_project_from_spec,
    fetch_and_validate_project,
)
from wandb.sdk.launch.builder.build import (
    construct_gcp_image_uri,
    docker_image_exists,
    generate_dockerfile,
    get_base_setup,
)

from .test_launch import (
    mocked_fetchable_git_repo,
    mocked_fetchable_git_repo_conda,
    mocked_fetchable_git_repo_nodeps,
)


def test_cuda_base_setup(test_settings, live_mock_server, mocked_fetchable_git_repo):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "cuda": True,
        "resource": "local",
        "resource_args": {},
        "docker": {
            "cuda_version": "11.0",
        },
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    base_setup = get_base_setup(test_project, "3.7", "3")
    assert "FROM nvidia/cuda:11.0-runtime as base" in base_setup
    assert "python3-pip" in base_setup and "python3-setuptools" in base_setup


def test_py2_cuda_base_setup(
    test_settings, live_mock_server, mocked_fetchable_git_repo
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "cuda": True,
        "resource": "local",
        "resource_args": {},
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    base_setup = get_base_setup(test_project, "2.7", "2")
    assert "FROM nvidia/cuda:" in base_setup
    assert "python-pip" in base_setup and "python-setuptools" in base_setup


def test_run_cuda_version(
    runner, live_mock_server, mocked_fetchable_git_repo, test_settings
):
    # run returns a previous cuda version = 11.0
    live_mock_server.set_ctx({"run_cuda_version": "11.0"})
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    # cuda unspecified, on by default
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "cuda": None,
        "resource": "local",
        "resource_args": {},
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    assert test_project.cuda is True
    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )
    assert "FROM nvidia/cuda:11.0-runtime as base" in dockerfile

    # cuda specified False, turned off
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "cuda": False,
        "resource": "local",
        "resource_args": {},
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    assert test_project.cuda is False
    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )
    assert "FROM python:" in dockerfile

    # differing versions, use specified
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "cuda": True,
        "resource": "local",
        "resource_args": {},
        "docker": {
            "cuda_version": "10.0",
        },
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    assert test_project.cuda is True
    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )
    assert "FROM nvidia/cuda:10.0-runtime as base" in dockerfile


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
        "cuda": False,
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
        "cuda": False,
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


def test_buildx_not_installed(
    test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):
    monkeypatch.setattr("wandb.docker.is_buildx_installed", lambda: False)

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "cuda": None,
        "resource": "local",
        "resource_args": {},
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)

    dockerfile = generate_dockerfile(
        test_project, EntryPoint("main.py", ["python", "train.py"]), "local", "docker"
    )

    assert "RUN WANDB_DISABLE_CACHE=true" in dockerfile


def test_gcp_uri(test_settings, live_mock_server, mocked_fetchable_git_repo):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    test_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
        "cuda": None,
        "resource": "local",
        "resource_args": {},
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)

    uri = construct_gcp_image_uri(
        test_project, "test-repo", "test-project", "test-registry"
    )
    assert (
        "test-registry/test-project/test-repo/wandb.aimock_server_entitytestruns1:68747470733a2f2f666f6f3a62617240"
        in uri
    )


def test_docker_image_exists(
    test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):
    def raise_docker_error(args):
        raise DockerError(args, 1, b"", b"")

    monkeypatch.setattr(wandb.docker, "run", lambda args: raise_docker_error(args))
    assert docker_image_exists("test:image") == False
