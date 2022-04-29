import json
import os
import platform
from unittest import mock
from unittest.mock import MagicMock
import sys
import yaml

import pytest
import wandb
from wandb.apis import PublicApi
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.builder.build import pull_docker_image
import wandb.sdk.launch.launch as launch
from wandb.sdk.launch.builder.docker import DockerBuilder
from wandb.sdk.launch.launch_add import launch_add
import wandb.sdk.launch._project_spec as _project_spec
from wandb.sdk.launch.utils import (
    LAUNCH_CONFIG_FILE,
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)
import wandb.util as util

from ..utils import fixture_open, notebook_path

from .test_launch import (
    mocked_fetchable_git_repo,
)

EMPTY_BACKEND_CONFIG = {
    PROJECT_DOCKER_ARGS: {},
    PROJECT_SYNCHRONOUS: True,
}

@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions < 3.5",
)
def test_launch_bare_base_case(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    monkeypatch,
    capsys
):

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    # for now using mocks instead of mock server
    def mocked_download_url(*args, **kwargs):
        if args[1] == "wandb-metadata.json":
            return {"url": "urlForCodePath"}
        elif args[1] == "code/main2.py":
            return {"url": "main2.py"}
        elif args[1] == "requirements.txt":
            return {"url": "requirements"}

    api.download_url = MagicMock(side_effect=mocked_download_url)

    def mocked_file_download_request(url):
        class MockedFileResponder:
            def __init__(self, url):
                self.url: str = url

            def json(self):
                if self.url == "urlForCodePath":
                    return {"codePath": "main2.py"}

            def iter_content(self, chunk_size):
                if self.url == "requirements":
                    # TODO: Feed this into 
                    return [b"numpy==1.19.5\n", b"wandb==1.0.0\n"]
                elif self.url == "main2.py":
                    return [
                        b"import numpy\n",
                        b"import wandb\n",
                        b"open('/tmp/test.txt', 'w').write('Success!')\n",
                    ]

        return 200, MockedFileResponder(url)
    api.download_file = MagicMock(side_effect=mocked_file_download_request)



    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "bare",
    }
    run = launch.run(**kwargs)
    run.wait()

    outerr = capsys.readouterr()
    breakpoint()

    assert (
        "Attempting to log a sequence of Image objects from multiple processes might result in data loss. Please upgrade your wandb server"
        in outerr.err
    )

    breakpoint()
