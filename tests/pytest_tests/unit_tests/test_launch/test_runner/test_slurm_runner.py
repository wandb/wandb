import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.runner.slurm_monitor import SlurmJob
from wandb.sdk.launch.runner.slurm_runner import SlurmRunner, SlurmSubmittedRun


@pytest.fixture
def mock_launch_project():
    """Mock the launch project for testing."""
    project = MagicMock(spec=LaunchProject)
    project.override_args = ["--epochs", "10"]
    os.makedirs("wandb/jobs/test_project", exist_ok=True)
    project.project_dir = Path("wandb/jobs/test_project")
    project.slurm_env_name = "test_env"
    project.run_id = "test_run_id"
    project.override_entrypoint = None
    project.get_job_entry_point = MagicMock(
        return_value=EntryPoint("slurm.sh", ["sbatch", "slurm.sh"])
    )
    project.get_env_vars_dict = MagicMock(
        return_value={
            "WANDB_API_KEY": "test_api_key",
            "WANDB_PROJECT": "test_project",
            "WANDB_ENTITY": "test_entity",
            "WANDB_LAUNCH": "true",
        }
    )
    project.fill_macros = MagicMock(
        return_value={
            "slurm": {
                "sbatch": {"partition": "gpu", "time": "1:00:00"},
                "run": {},
            }
        }
    )
    return project


@pytest.fixture
def mock_launch_slurm_job(mocker):
    """Mock the function that actually launches the Slurm job for testing."""
    mock_job = AsyncMock(spec=SlurmSubmittedRun)
    mock_job.id = "12345"
    mock_launch = AsyncMock(return_value=mock_job)
    mocker.patch(
        "wandb.sdk.launch.runner.slurm_runner.launch_slurm_job",
        mock_launch,
    )
    return mock_launch


@pytest.mark.asyncio
async def test_slurm_runner(
    test_api,
    mock_launch_project,
    mock_launch_slurm_job,
    monkeypatch,
):
    """Test that the Slurm runner runs correctly.

    The Slurm runner should infer a command and location to run it
    from the launch project and then run the command by calling launch_slurm_job.
    We mock this and check that the call was made with the correct arguments.
    """
    runner = SlurmRunner(test_api, {"SYNCHRONOUS": "true"})
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "test_env")
    await runner.run(mock_launch_project, "test_env")

    assert mock_launch_slurm_job.call_count == 1
    call_args = mock_launch_slurm_job.call_args[0]

    assert call_args[0] == mock_launch_project
    assert call_args[1] == {}  # run_args
    assert call_args[2] == [
        "conda",
        "run",
        "-n",
        "test_env",
        "sbatch",
        "--comment=wandb-run-id:test_run_id",
        "--partition=gpu",
        "--time=1:00:00",
        "slurm.sh",
        "--epochs",
        "10",
    ]
    assert "WANDB_API_KEY" in call_args[3]
    assert "WANDB_PROJECT" in call_args[3]
    assert "WANDB_ENTITY" in call_args[3]
    assert "CONDA_DEFAULT_ENV" in call_args[3]
    assert call_args[4]  # synchronous
