import json
import multiprocessing.pool
import os
import sys
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.sdk.launch._launch as _launch
import yaml
from wandb.sdk.launch._project_spec import (
    LaunchError,
    LaunchProject,
    LaunchSource,
    _inject_wandb_config_env_vars,
)
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.builder.docker_builder import DockerBuilder
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.utils import (
    LAUNCH_DEFAULT_PROJECT,
    PROJECT_SYNCHRONOUS,
    pull_docker_image,
)
from wandb.sdk.lib import runid

from tests.pytest_tests.unit_tests_old.utils import fixture_open, notebook_path

EMPTY_BACKEND_CONFIG = {
    PROJECT_SYNCHRONOUS: True,
}


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


class MockBranch:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def mocked_fetchable_git_repo():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        repo = mock.Mock()
        reference = MockBranch("master")
        repo.references = [reference]
        repo.refs = {"master": mock.Mock()}

        def create_remote(o, r):
            origin = mock.Mock()
            origin.refs = {"master": mock.Mock()}
            return origin

        repo.create_remote = create_remote
        repo.heads = {"master": mock.Mock()}
        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        return repo

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


@pytest.fixture
def mocked_fetchable_git_repo_conda():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        repo = mock.Mock()
        reference = MockBranch("master")
        repo.references = [reference]

        def create_remote(o, r):
            origin = mock.Mock()
            origin.refs = {"master": mock.Mock()}
            return origin

        repo.create_remote = create_remote
        repo.heads = {"master": mock.Mock()}

        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "environment.yml"), "w") as f:
            f.write(fixture_open("environment.yml").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        return repo

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


@pytest.fixture
def mocked_fetchable_git_repo_ipython():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        repo = mock.Mock()
        reference = MockBranch("master")
        repo.references = [reference]

        def create_remote(o, r):
            origin = mock.Mock()
            origin.refs = {"master": mock.Mock()}
            return origin

        repo.create_remote = create_remote
        repo.heads = {"master": mock.Mock()}

        with open(os.path.join(dst_dir, "one_cell.ipynb"), "w") as f:
            f.write(open(notebook_path("one_cell.ipynb")).read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        return repo

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


@pytest.fixture
def mocked_fetchable_git_repo_nodeps():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        repo = mock.Mock()
        reference = MockBranch("master")
        repo.references = [reference]

        def create_remote(o, r):
            origin = mock.Mock()
            origin.refs = {"master": mock.Mock()}
            return origin

        repo.create_remote = create_remote
        repo.heads = {"master": mock.Mock()}

        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        return repo

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


@pytest.fixture
def mocked_fetchable_git_repo_shell():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        repo = mock.Mock()
        reference = MockBranch("master")
        repo.references = [reference]

        def create_remote(o, r):
            origin = mock.Mock()
            origin.refs = {"master": mock.Mock()}
            return origin

        repo.create_remote = create_remote
        repo.heads = {"master": mock.Mock()}

        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        with open(os.path.join(dst_dir, "test.sh"), "w") as f:
            f.write("python train.py")
        with open(os.path.join(dst_dir, "unknown.unk"), "w") as f:
            f.write("test")
        return repo

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


@pytest.fixture
def mock_load_backend():
    def side_effect(*args, **kwargs):
        mock_props = mock.Mock()
        mock_props.args = args
        mock_props.kwargs = kwargs
        return mock_props

    with mock.patch("wandb.sdk.launch.loader.runner_from_config") as mock_load_backend:
        m = mock.Mock(side_effect=side_effect)
        m.run = AsyncMock(side_effect=side_effect, return_value=mock.Mock())
        mock_load_backend.return_value = m
        yield mock_load_backend


@pytest.fixture
def mock_load_backend_agent():
    def side_effect(*args, **kwargs):
        mock_props = mock.Mock()
        mock_props.args = args
        mock_props.kwargs = kwargs
        return mock_props

    with mock.patch("wandb.sdk.launch.agent.agent.load_backend") as mock_load_backend:
        m = mock.Mock(side_effect=side_effect)
        m.run = mock.Mock(side_effect=side_effect)
        mock_load_backend.return_value = m
        yield mock_load_backend


def code_download_func(dst_dir):
    with open(os.path.join(dst_dir, "train.py"), "w") as f:
        f.write(fixture_open("train.py").read())
    with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
        f.write(fixture_open("requirements.txt").read())
    with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
        f.write("testing")


def mock_download_url(*args, **kwargs):
    if args[1] == "wandb-metadata.json":
        return {"url": "urlForCodePath"}
    elif args[1] == "code/main2.py":
        return {"url": "main2.py"}
    elif args[1] == "requirements.txt":
        return {"url": "requirements"}


def mock_file_download_request(url):
    class MockedFileResponder:
        def __init__(self, url):
            self.url: str = url

        def json(self):
            if self.url == "urlForCodePath":
                return {"codePath": "main2.py"}

        def iter_content(self, chunk_size):
            if self.url == "requirements":
                return [b"numpy==1.19.5\n", b"wandb==0.12.15\n"]
            elif self.url == "main2.py":
                return [
                    b"import numpy\n",
                    b"import wandb\n",
                    b"import time\n",
                    b"print('(main2.py) starting')\n",
                    b"time.sleep(1)\n",
                    b"print('(main2.py) finished')\n",
                ]

    return 200, MockedFileResponder(url)


def check_project_spec(
    project_spec,
    api,
    uri=None,
    job=None,
    project=None,
    entity=None,
    launch_config=None,
    resource="local-container",
    resource_args=None,
    docker_image=None,
):
    assert project_spec.uri == uri
    assert project_spec.job == job
    expected_project = project or uri.split("/")[4]
    assert project_spec.target_project == expected_project
    expected_target_entity = entity or api.default_entity
    assert project_spec.target_entity == expected_target_entity
    if (
        launch_config
        and launch_config.get("config")
        and launch_config["config"].get("overrides")
        and launch_config["config"]["overrides"].get("run_config")
    ):
        assert (
            project_spec.override_config
            == launch_config["config"]["overrides"]["run_config"]
        )
    assert project_spec.resource == resource
    if resource_args:
        assert {(k, v) for k, v in resource_args.items()} == {
            (k, v) for k, v in project_spec.resource_args.items()
        }
    if project_spec.source == LaunchSource.WANDB:
        with open(os.path.join(project_spec.project_dir, "patch.txt")) as fp:
            contents = fp.read()
            assert contents == "testing"
    assert project_spec.image_name is not None


def check_backend_config(config, expected_backend_config):
    for key, item in config.items():
        assert item == expected_backend_config[key]


def check_mock_run_info(mock_with_run_info, expected_backend_config, kwargs):
    for arg in mock_with_run_info.args:
        if isinstance(arg, LaunchProject):
            check_project_spec(arg, **kwargs)
        if isinstance(arg, dict):
            check_backend_config(arg, expected_backend_config)
    for arg in mock_with_run_info.kwargs.items():
        if isinstance(arg, LaunchProject):
            check_project_spec(arg, **kwargs)
        if isinstance(arg, dict):
            check_backend_config(arg, expected_backend_config)


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions < 3.5",
)
@pytest.mark.asyncio
async def test_launch_base_case(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    mock_load_backend,
    monkeypatch,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
    }
    mock_with_run_info = await _launch._launch(**kwargs)
    check_mock_run_info(mock_with_run_info, EMPTY_BACKEND_CONFIG, kwargs)


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions < 3.5",
)
@pytest.mark.asyncio
async def test_launch_resource_args(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
        "resource": "local-container",
        "resource_args": {"a": "b", "c": "d"},
    }
    mock_with_run_info = await _launch._launch(**kwargs)
    check_mock_run_info(mock_with_run_info, EMPTY_BACKEND_CONFIG, kwargs)


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions <3.5",
)
@pytest.mark.asyncio
async def test_launch_specified_project(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
    mock_load_backend,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "api": api,
        "project": "new_test_project",
        "entity": "mock_server_entity",
    }
    mock_with_run_info = await _launch._launch(**kwargs)
    check_mock_run_info(mock_with_run_info, EMPTY_BACKEND_CONFIG, kwargs)


@pytest.mark.asyncio
async def test_launch_run_config_in_spec(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "api": api,
        "project": "new_test_project",
        "entity": "mock_server_entity",
        "launch_config": {"overrides": {"run_config": {"epochs": 3}}},
    }

    expected_runner_config = {}
    mock_with_run_info = await _launch._launch(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_runner_config, kwargs)


# this test includes building a docker container which can take some time,
# hence the timeout. caching should usually keep this under 30 seconds
@pytest.mark.flaky
@pytest.mark.timeout(320)
@pytest.mark.skip(reason="this test is flaky and should be re-enabled with WB7616")
def test_launch_agent_runs(
    test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):
    monkeypatch.setattr(
        wandb.sdk.launch.agent.LaunchAgent,
        "pop_from_queue",
        lambda c, queue: patched_pop_from_queue(c, queue),
    )

    def mock_raise_exception():
        raise Exception

    monkeypatch.setattr(
        multiprocessing.pool.Pool,
        "apply_async",
        lambda x, y: mock_raise_exception(),
    )
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    api.entity_is_team = MagicMock(return_value=False)
    config = {
        "entity": "mock_server_entity",
        "project": "test",
    }
    _launch.create_and_run_agent(api, config)
    ctx = live_mock_server.get_ctx()
    assert ctx["num_popped"] == 1
    assert len(ctx["launch_agents"].keys()) == 1


def test_launch_agent_instance(test_settings, live_mock_server):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    api.entity_is_team = MagicMock(return_value=False)
    config = {
        "entity": "mock_server_entity",
        "project": "test_project",
        "queues": ["default"],
    }
    agent = LaunchAgent(api, config)
    ctx = live_mock_server.get_ctx()
    assert len(ctx["launch_agents"]) == 1
    assert agent._id == int(list(ctx["launch_agents"].keys())[0])

    get_agent_response = api.get_launch_agent(agent._id, agent.gorilla_supports_agents)
    assert get_agent_response["name"] == "test_agent"

def test_agent_no_introspection(test_settings, live_mock_server):
    live_mock_server.set_ctx({"gorilla_supports_launch_agents": False})
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    api.entity_is_team = MagicMock(return_value=False)
    config = {
        "entity": "mock_server_entity",
        "project": "test_project",
        "queues": ["default"],
    }
    agent = LaunchAgent(api, config)
    ctx = live_mock_server.get_ctx()
    assert ctx["launch_agents"] == {}
    assert len(ctx["launch_agents"].keys()) == 0
    assert agent._id is None
    assert agent._name == ""

    update_response = api.update_launch_agent_status(
        agent._id, "POLLING", agent.gorilla_supports_agents
    )
    assert update_response["success"]

    get_agent_response = api.get_launch_agent(agent._id, agent.gorilla_supports_agents)
    assert get_agent_response["name"] == ""
    assert get_agent_response["stopPolling"] is False


@pytest.mark.timeout(320)
@pytest.mark.skip(reason="The nb tests are now run against the unmock server.")
@pytest.mark.asyncio
async def test_launch_notebook(
    live_mock_server, test_settings, mocked_fetchable_git_repo_ipython, monkeypatch
):
    # TODO: make this test work with the unmock server
    live_mock_server.set_ctx({"run_script_type": "notebook"})

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    run = await _launch._launch(
        api=api,
        uri="https://wandb.ai/mock_server_entity/test/runs/jupyter1",
        project="new-test",
    )
    assert str(run.get_status()) == "finished"


@pytest.mark.timeout(320)
@pytest.mark.asyncio
async def test_launch_no_server_info(
    live_mock_server, test_settings, mocked_fetchable_git_repo
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    api.get_run_info = MagicMock(
        return_value=None, side_effect=wandb.CommError("test comm error")
    )
    try:
        await _launch._launch(
            api=api,
            uri="https://wandb.ai/mock_server_entity/test/runs/1",
            project="new-test",
        )
    except LaunchError as e:
        assert "Run info is invalid or doesn't exist" in str(e)


@pytest.mark.flaky
@pytest.mark.xfail(reason="test goes through flaky periods. Re-enable with WB7616")
@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_launch_metadata(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    api.download_url = mock_download_url
    api.download_file = mock_file_download_request

    run = await _launch._launch(
        api=api,
        uri="https://wandb.ai/mock_server_entity/test/runs/1",
        project="test-another-new-project",
    )
    assert str(run.get_status()) == "finished"


async def patched_pop_from_queue(self, queue):
    ups = self._api.pop_from_run_queue(
        queue, entity=self._entity, project=self._project
    )
    if not ups:
        raise KeyboardInterrupt
    return ups



@pytest.mark.asyncio
async def test_launch_url_and_job(
    live_mock_server,
    test_settings,
):
    api = MagicMock()
    with pytest.raises(LaunchError) as e_info:
        await _launch._launch(
            api=api,
            uri="https://wandb.ai/mock_server_entity/test/runs/1",
            job="test/test/test-job:v0",
            project="new-test",
        )
    assert "Must specify exactly one of uri, job or image" in str(e_info)


@pytest.mark.asyncio
async def test_launch_no_url_job_or_docker_image(
    live_mock_server,
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    api.get_run_info = MagicMock(
        return_value=None, side_effect=wandb.CommError("test comm error")
    )
    try:
        await _launch._launch(
            api=api,
            uri=None,
            job=None,
            project="new-test",
        )
    except LaunchError as e:
        assert "Must specify a uri, job or docker image" in str(e)