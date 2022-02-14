import json
import os
from unittest import mock
from unittest.mock import MagicMock
import sys

import pytest
import wandb
from wandb.sdk.launch._project_spec import (
    create_project_from_spec,
    fetch_and_validate_project,
)
from wandb.sdk.launch.docker import (
    generate_dockerfile,
    get_base_setup,
    get_env_vars_section,
)

from .test_launch import mocked_fetchable_git_repo, mocked_fetchable_git_repo_conda


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
        "docker": {"cuda_version": "11.0",},
    }
    test_project = create_project_from_spec(test_spec, api)
    test_project = fetch_and_validate_project(test_project, api)
    base_setup = get_base_setup(test_project, "3.7", "3")
    assert "FROM nvidia/cuda:11.0-runtime as base" in base_setup
    assert "python3-pip" in base_setup and "python3-setuptools" in base_setup


def test_dockerfile_conda(
    test_settings, live_mock_server, mocked_fetchable_git_repo_conda
):
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
        api, test_project, test_project.get_single_entry_point()
    )
    assert "conda env create -f environment.yml" in dockerfile
    assert "FROM continuumio/miniconda3:latest as build" in dockerfile


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
        api, test_project, test_project.get_single_entry_point()
    )

    assert "RUN WANDB_DISABLE_CACHE=true" in dockerfile
