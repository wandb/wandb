from unittest.mock import MagicMock, AsyncMock

import pytest
from wandb.sdk.launch._project_spec import EntryPoint, LaunchProject
from wandb.sdk.launch.runner.slurm_runner import SlurmRunner, SlurmSubmittedRun
from wandb.sdk.launch.runner.slurm_monitor import SlurmJob


@pytest.fixture
def mock_launch_project():
    """Mock the launch project for testing."""
    project = MagicMock(spec=LaunchProject)
    project.override_entrypoint = EntryPoint("train.py", ["python", "train.py"])
    project.override_args = ["--epochs", "10"]
    project.project_dir = "/tmp/project_dir"
    project.slurm_env_name = "test_env"
    project.run_id = "test_run_id"
    project.get_env_vars_dict = MagicMock(
        return_value={
            "WANDB_API_KEY": "test_api_key",
            "WANDB_PROJECT": "test_project",
            "WANDB_ENTITY": "test_entity",
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
    test_settings,
    test_api,
    mock_launch_project,
    mock_launch_slurm_job,
):
    """Test that the Slurm runner runs correctly.

    The Slurm runner should infer a command and location to run it
    from the launch project and then run the command by calling launch_slurm_job.
    We mock this and check that the call was made with the correct arguments.
    """
    runner = SlurmRunner(test_api, {"SYNCHRONOUS": "true"})
    await runner.run(mock_launch_project, "test_image_uri")

    assert mock_launch_slurm_job.call_count == 1
    call_args = mock_launch_slurm_job.call_args[0]
    
    assert call_args[0] == mock_launch_project
    assert call_args[1] == {}  # run_args
    assert call_args[2] == [
        "sbatch",
        "--comment=wandb-run-id:test_run_id",
        "--partition=gpu",
        "--time=1:00:00",
        "python",
        "train.py",
        "--epochs",
        "10",
    ]
    assert "WANDB_API_KEY" in call_args[3]
    assert "WANDB_PROJECT" in call_args[3]
    assert "WANDB_ENTITY" in call_args[3]
    assert call_args[4] == True  # synchronous
