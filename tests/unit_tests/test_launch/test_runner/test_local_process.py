from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wandb.sdk.launch._project_spec import EntryPoint
from wandb.sdk.launch.runner.local_process import LocalProcessRunner


@pytest.fixture
def mock_launch_project():
    """Mock the launch project for testing."""
    project = MagicMock()
    project.override_entrypoint = EntryPoint("train.py", ["python", "train.py"])
    project.override_args = ["--epochs", "10"]
    project.project_dir = "/tmp/project_dir"
    project.get_env_vars_dict = MagicMock(
        return_value={
            "WANDB_API_KEY": "test_api_key",
            "WANDB_PROJECT": "test_project",
            "WANDB_ENTITY": "test_entity",
        }
    )
    return project


@pytest.fixture
def mock_run_entry_point(mocker):
    """Mock the function that actually runs the entrypoint for testing."""
    mock_run = MagicMock()

    async def _mock_wait():
        return

    mock_run.wait = _mock_wait
    mock_run_entry_point = MagicMock(return_value=mock_run)

    mocker.patch(
        "wandb.sdk.launch.runner.local_process._run_entry_point",
        mock_run_entry_point,
    )
    return mock_run_entry_point


@pytest.mark.asyncio
async def test_local_process_runner(
    test_settings,
    test_api,
    mock_launch_project,
    mock_run_entry_point,
):
    """Test that the local process runner runs correctly.

    The local process runner should infer a command and location to run it
    from the launch project and then run the command by calling _run_entry_point
    imported from local_container.py. We mock this and check that the call was
    made with the correct arguments.
    """
    runner = LocalProcessRunner(test_api, {"SYNCHRONOUS": "true"})
    await runner.run(mock_launch_project)

    assert mock_run_entry_point.call_count == 1
    assert (
        mock_run_entry_point.call_args[0][0]
        == "WANDB_API_KEY=test_api_key WANDB_PROJECT=test_project "
        "WANDB_ENTITY=test_entity python train.py --epochs 10"
    )
    assert mock_run_entry_point.call_args[0][1] == "/tmp/project_dir"
