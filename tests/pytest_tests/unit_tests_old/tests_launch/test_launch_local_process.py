import sys

import pytest
import wandb
import wandb.sdk.launch.launch as launch
from wandb.sdk.launch.utils import PROJECT_DOCKER_ARGS, PROJECT_SYNCHRONOUS

from .test_launch import (
    mock_download_url,
    mock_file_download_request,
    mocked_fetchable_git_repo,
)


# todo: MLW folk, please help!
@pytest.mark.xfail(
    reason="Something is not right since we moved the test to a different dir"
)
def test_launch_local_process_base_case(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    monkeypatch,
    capsys,
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
        "resource": "local-process",
    }
    run = launch.run(**kwargs)
    run.wait()
    assert str(run.get_status()) == "finished"
    # # TODO: Why does this not work?
    # _, err = capsys.readouterr()
    # assert "(main2.py) finished" in out
