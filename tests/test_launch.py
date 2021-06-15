import os
from unittest import mock

import wandb
import wandb.sdk.launch as launch
from .utils import fixture_open
import pytest

@pytest.fixture
def mocked_fetchable_git_repo():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        return mock.Mock()

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    yield m

def test_launch_base_case(runner, live_mock_server, test_settings, parse_ctx, mocked_fetchable_git_repo):

    with mock.patch.dict("sys.modules", git=mocked_fetchable_git_repo):
        with runner.isolated_filesystem():
            api = wandb.sdk.internal.internal_api.Api(
                default_settings=test_settings, load_settings=False
            )
            launch.run(
                "https://wandb.ai/mock_server_entity/test-project/runs/1",
                config={},
                api=api,
            )
    ctx_util = parse_ctx(live_mock_server.get_ctx())
    assert live_mock_server.get_ctx()["fail_graphql_count"] == 0
    assert ctx_util.config["epochs"]["value"] == 2

