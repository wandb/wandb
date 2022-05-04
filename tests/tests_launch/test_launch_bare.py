import sys

import pytest
import wandb
import wandb.sdk.launch.launch as launch
from wandb.sdk.launch.utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)

from .test_launch import (
    mocked_fetchable_git_repo,
    mock_download_url,
    mock_file_download_request,
)


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions < 3.5",
)
def test_launch_bare_base_case(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    monkeypatch,
):

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    api.download_url = mock_download_url
    api.download_file = mock_file_download_request

    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "bare",
        "synchronous": False,
    }
    run = launch.run(**kwargs)

    assert run.command_proc.stdout.readline() == "... Done!"
    assert str(run.get_status()) == "finished"
