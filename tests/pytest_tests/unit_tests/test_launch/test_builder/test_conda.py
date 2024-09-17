import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.builder.conda_builder import CondaBuilder
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.lib.filenames import FROZEN_CONDA_FNAME


@pytest.fixture
def mock_environment():
    return Mock()


@pytest.fixture
def mock_registry():
    return Mock()


@pytest.fixture
def conda_builder(mock_environment, mock_registry):
    return CondaBuilder(
        {"resource": "slurm"}, mock_environment, mock_registry, verify=False
    )


@pytest.fixture
def mock_launch_project():
    project = Mock(spec=LaunchProject)
    project.job_build_context = None
    project.project_dir = os.getcwd()
    dir = Path(project.project_dir)
    requirements_file = dir / "conda.frozen.yml"
    requirements_file.write_text("name: test_env\ndependencies:\n  - python=3.8\n")
    slurm = dir / "slurm.sh"
    slurm.write_text("#!/bin/bash\nsrun python train.py\n")
    os.makedirs(Path(os.getcwd()) / "venvs", exist_ok=True)
    project.slurm_env_dir = Path(os.getcwd()) / "venvs" / "test_env"
    project.python_version = "3.8"
    project.resource_args = {"slurm": {"conda-env": "test_env"}}
    return project


@pytest.fixture
def mock_entrypoint():
    return Mock(spec=EntryPoint, command=["python", "train.py"])


def test_conda_builder_initialization(mock_environment, mock_registry):
    builder_config = {"resource": "slurm"}
    builder = CondaBuilder(builder_config, mock_environment, mock_registry)

    assert builder.environment == mock_environment
    assert builder.registry == mock_registry
    assert builder.builder_config == builder_config
    assert builder.verify


@patch("wandb.sdk.launch.builder.conda_builder.subprocess.check_call")
@patch(
    "builtins.open",
    new_callable=unittest.mock.mock_open,
    read_data="python=3.8\nwandb==0.10.0\n",
)
def test_create_conda_env(
    mock_open, mock_check_call, conda_builder, mock_launch_project
):
    conda_builder._create_conda_env(mock_launch_project)

    mock_check_call.assert_called_once_with(
        [
            "conda",
            "env",
            "create",
            "-f",
            str(Path(mock_launch_project.project_dir) / FROZEN_CONDA_FNAME),
            "-p",
            mock_launch_project.slurm_env_dir,
        ]
    )


@patch(
    "builtins.open",
    new_callable=unittest.mock.mock_open,
    read_data="#!/bin/bash\nsrun python train.py\n",
)
def test_modify_entrypoint(mock_open, conda_builder, mock_launch_project):
    entrypoint_path = Path("/tmp/test_project/slurm.sh")
    conda_builder._modify_entrypoint(mock_launch_project, entrypoint_path)

    mock_open().writelines.assert_called_once()
    written_content = "".join(mock_open().writelines.call_args[0][0])
    assert f"conda activate {mock_launch_project.slurm_env_dir}" in written_content


@pytest.mark.asyncio
@patch("wandb.sdk.launch.builder.conda_builder.list_conda_envs", return_value=[])
@patch("wandb.sdk.launch.builder.conda_builder.CondaBuilder._create_conda_env")
@patch("wandb.sdk.launch.builder.conda_builder.CondaBuilder._modify_entrypoint")
async def test_build_image(
    mock_list,
    mock_create,
    mock_modify,
    conda_builder,
    mock_launch_project,
    mock_entrypoint,
):
    result = await conda_builder.build_image(mock_launch_project, mock_entrypoint)

    mock_create.assert_called_once_with(mock_launch_project)
    mock_modify.assert_called_once()
    assert result == mock_launch_project.slurm_env_dir


@pytest.mark.asyncio
@patch(
    "wandb.sdk.launch.builder.conda_builder.list_conda_envs", return_value=["test_env"]
)
async def test_build_image_existing_env(
    mock_list, conda_builder, mock_launch_project, mock_entrypoint
):
    result = await conda_builder.build_image(mock_launch_project, mock_entrypoint)

    assert result == "test_env"


@pytest.mark.asyncio
@patch("pathlib.Path.exists", return_value=False)
async def test_build_image_no_entrypoint(
    mock_exists, conda_builder, mock_launch_project, mock_entrypoint
):
    with pytest.raises(LaunchError):
        await conda_builder.build_image(mock_launch_project, mock_entrypoint)
