import json
import multiprocessing.pool
import os
import sys
from unittest import mock
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.sdk.launch._launch as _launch
import wandb.sdk.launch._project_spec as _project_spec
import yaml
from wandb.apis import PublicApi
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.builder.build import _inject_wandb_config_env_vars
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
    if project_spec.source == _project_spec.LaunchSource.WANDB:
        with open(os.path.join(project_spec.project_dir, "patch.txt")) as fp:
            contents = fp.read()
            assert contents == "testing"
    assert project_spec.image_name is not None


def check_backend_config(config, expected_backend_config):
    for key, item in config.items():
        assert item == expected_backend_config[key]


def check_mock_run_info(mock_with_run_info, expected_backend_config, kwargs):
    for arg in mock_with_run_info.args:
        if isinstance(arg, _project_spec.LaunchProject):
            check_project_spec(arg, **kwargs)
        if isinstance(arg, dict):
            check_backend_config(arg, expected_backend_config)
    for arg in mock_with_run_info.kwargs.items():
        if isinstance(arg, _project_spec.LaunchProject):
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
async def test_launch_unowned_project(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "uri": "https://wandb.ai/other_user/test_project/runs/1",
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


@pytest.mark.asyncio
async def test_launch_code_artifact(
    runner, live_mock_server, test_settings, monkeypatch, mock_load_backend
):
    run_with_artifacts = mock.MagicMock()
    code_artifact = mock.MagicMock()
    code_artifact.type = "code"
    code_artifact.download = code_download_func
    code_artifact.digest = "abc123"

    run_with_artifacts.logged_artifacts.return_value = [code_artifact]
    monkeypatch.setattr(
        wandb.PublicApi, "run", lambda *arg, **kwargs: run_with_artifacts
    )

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


def test_agent_queues_notfound(test_settings, live_mock_server):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    config = {
        "entity": "mock_server_entity",
        "project": "test_project",
        "queues": ["nonexistent_queue"],
    }
    try:
        _launch.create_and_run_agent(api, config)
    except Exception as e:
        assert (
            "Could not start launch agent: Not all of requested queues (nonexistent_queue) found"
            in str(e)
        )


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


def test_agent_inf_jobs(test_settings, live_mock_server):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    api.entity_is_team = MagicMock(return_value=False)
    config = {
        "entity": "mock_server_entity",
        "project": "test_project",
        "queues": ["default"],
        "max_jobs": -1,
    }
    agent = LaunchAgent(api, config)
    assert agent._max_jobs == float("inf")


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


def test_fail_pull_docker_image():
    try:
        pull_docker_image("not an image")
    except LaunchError as e:
        assert "Docker server returned error" in str(e)


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions < 3.5",
)
@pytest.mark.asyncio
async def test_bare_wandb_uri(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    uri = "/mock_server_entity/test/runs/12345678"
    kwargs = {
        "uri": uri,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
    }

    mock_with_run_info = await _launch._launch(**kwargs)
    kwargs["uri"] = live_mock_server.base_url + uri
    check_mock_run_info(mock_with_run_info, EMPTY_BACKEND_CONFIG, kwargs)


@pytest.mark.asyncio
async def test_launch_project_spec_docker_image(
    live_mock_server, test_settings, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    kwargs = {
        "uri": None,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
        "docker_image": "my-image:v0",
    }

    mock_with_run_info = await _launch._launch(**kwargs)

    check_mock_run_info(mock_with_run_info, {}, kwargs)


@pytest.mark.asyncio
async def test_launch_local_docker_image(live_mock_server, test_settings, monkeypatch):
    monkeypatch.setattr("wandb.sdk.launch.utils.docker_image_exists", lambda x: True)
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container.pull_docker_image", lambda x: True
    )
    monkeypatch.setattr(
        "wandb.sdk.launch.runner.local_container._run_entry_point",
        lambda cmd, project_dir: (cmd, project_dir),
    )
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    image_name = "my-image:v0"
    kwargs = {
        "uri": None,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
        "docker_image": image_name,
        "synchronous": False,
        "resource_args": {
            "local-container": {
                "volume": [
                    "/test-volume:/test-volume",
                    "/test-volume-2:/test-volume-2",
                ],
                "env": ["TEST_ENV=test-env", "FROM_MY_ENV"],
                "t": True,
            }
        },
        "run_id": "p5leu4a7",
    }
    expected_command = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"WANDB_BASE_URL={live_mock_server.base_url}",
        "-e",
        f"WANDB_API_KEY={api.settings('api_key')}",
        "-e",
        "WANDB_PROJECT=test",
        "-e",
        "WANDB_ENTITY=mock_server_entity",
        "-e",
        "WANDB_LAUNCH=True",
        "-e",
        "WANDB_RUN_ID=p5leu4a7",
        "-e",
        f"WANDB_DOCKER={image_name}",
        "-e",
        "WANDB_CONFIG='{}'",
        "-e",
        "WANDB_ARTIFACTS='{}'",
        "--volume",
        "/test-volume:/test-volume",
        "--volume",
        "/test-volume-2:/test-volume-2",
        "--env",
        "TEST_ENV=test-env",
        "--env",
        "FROM_MY_ENV",
        "-t",
        "--network",
        "host",
    ]
    if sys.platform == "linux" or sys.platform == "linux2":
        expected_command += ["--add-host", "host.docker.internal:host-gateway"]
    expected_command += [image_name]

    returned_command, project_dir = await _launch._launch(**kwargs)
    assert project_dir is None

    list_command = returned_command.split(" ")
    # exclude base url, since testing locally converts
    # localhost:port to host.docker.internal but not
    # in CI
    assert list_command[:4] == expected_command[:4]
    assert list_command[5:] == expected_command[5:]


def test_run_in_launch_context_with_config_env_var(
    runner, live_mock_server, test_settings, monkeypatch
):
    with runner.isolated_filesystem():
        config_env_var = json.dumps({"epochs": 10})
        monkeypatch.setenv("WANDB_CONFIG", config_env_var)
        test_settings.update(launch=True, source=wandb.sdk.wandb_settings.Source.INIT)
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        run.finish()
        assert run.config.epochs == 10
        assert run.config.lr == 0.004


def test_run_in_launch_context_with_multi_config_env_var(
    runner, live_mock_server, test_settings, monkeypatch
):
    with runner.isolated_filesystem():
        config_env_vars = {}
        _inject_wandb_config_env_vars({"epochs": 10}, config_env_vars, 5)
        for k in config_env_vars.keys():
            monkeypatch.setenv(k, config_env_vars[k])
        test_settings.update(launch=True, source=wandb.sdk.wandb_settings.Source.INIT)
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        run.finish()
        assert run.config.epochs == 10
        assert run.config.lr == 0.004


def test_run_in_launch_context_with_artifact_string_no_used_as_env_var(
    runner, live_mock_server, test_settings, monkeypatch
):
    live_mock_server.set_ctx({"swappable_artifacts": True})
    config_env_var = json.dumps(
        {"epochs": 10, "art": "wandb-artifact://mock_server_entity/test/old_name:v0"}
    )
    with runner.isolated_filesystem():
        monkeypatch.setenv("WANDB_ARTIFACTS", {})
        monkeypatch.setenv("WANDB_CONFIG", config_env_var)
        test_settings.update(launch=True, source=wandb.sdk.wandb_settings.Source.INIT)
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert run.config.art.name == "old_name:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "art"


def test_run_in_launch_context_with_artifact_no_used_as_env_var(
    runner, live_mock_server, test_settings, monkeypatch
):
    live_mock_server.set_ctx({"swappable_artifacts": True})
    arti = {
        "name": "test:v0",
        "project": "test",
        "entity": "test",
        "_version": "v0",
        "_type": "artifactVersion",
        "id": "QXJ0aWZhY3Q6NTI1MDk4",
    }
    # artifacts_env_var = json.dumps({"old_name:v0": arti})
    config_env_var = json.dumps({"epochs": 10})
    with runner.isolated_filesystem():
        monkeypatch.setenv("WANDB_ARTIFACTS", {"old_name:v0": arti})
        monkeypatch.setenv("WANDB_CONFIG", config_env_var)
        test_settings.update(launch=True, source=wandb.sdk.wandb_settings.Source.INIT)
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        arti_inst = run.use_artifact("old_name:v0")
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert arti_inst.name == "old_name:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "old_name:v0"


def test_run_in_launch_context_with_malformed_env_vars(
    runner, live_mock_server, test_settings, monkeypatch, capsys
):
    live_mock_server.set_ctx({"swappable_artifacts": True})
    with runner.isolated_filesystem():
        monkeypatch.setenv("WANDB_ARTIFACTS", '{"epochs: 6}')
        monkeypatch.setenv("WANDB_CONFIG", '{"old_name": {"name": "test:v0"')
        test_settings.update(launch=True, source=wandb.sdk.wandb_settings.Source.INIT)
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        run.finish()
        _, err = capsys.readouterr()
        assert "Malformed WANDB_CONFIG, using original config" in err
        assert "Malformed WANDB_ARTIFACTS, using original artifacts" in err


def test_launch_entrypoint(test_settings):
    entry_point = ["python", "main.py"]
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    launch_project = _project_spec.LaunchProject(
        "https://wandb.ai/mock_server_entity/test/runs/1",
        None,
        api,
        {},
        "live_mock_server_entity",
        "Test_project",
        None,
        {},
        {},
        {},
        "local-container",
        {},
        None,  # run_id
    )
    launch_project.set_entry_point(entry_point)
    calced_ep = launch_project.get_single_entry_point().compute_command(["--blah", "2"])
    assert calced_ep == ["python", "main.py", "--blah", "2"]


@pytest.mark.asyncio
async def test_launch_unknown_entrypoint(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo_shell,
):
    live_mock_server.set_ctx({"run_script_type": "unknown"})

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    with pytest.raises(LaunchError) as e_info:
        await _launch._launch(
            api=api,
            uri="https://wandb.ai/mock_server_entity/test/runs/shell1",
            project="new-test",
        )
    assert "Unsupported entrypoint:" in str(e_info.value)


def test_resolve_agent_config(monkeypatch, runner):
    monkeypatch.setattr(
        "wandb.sdk.launch._launch.LAUNCH_CONFIG_FILE",
        "./config/wandb/launch-config.yaml",
    )
    monkeypatch.setenv("WANDB_ENTITY", "diffentity")
    with runner.isolated_filesystem():
        os.makedirs("./config/wandb")
        with open("./config/wandb/launch-config.yaml", "w") as f:
            yaml.dump(
                {
                    "entity": "different-entity",
                    "max_jobs": 2,
                    "registry": {"url": "test"},
                },
                f,
            )
        config, returned_api = _launch.resolve_agent_config(
            None, None, -1, ["diff-queue"], None
        )

        assert config["registry"] == {"url": "test"}
        assert config["entity"] == "diffentity"
        assert config["max_jobs"] == -1
        assert config.get("project") == LAUNCH_DEFAULT_PROJECT


@pytest.mark.asyncio
async def test_launch_url_and_job(
    live_mock_server,
    test_settings,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    api.get_run_info = MagicMock(
        return_value=None, side_effect=wandb.CommError("test comm error")
    )
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


@pytest.fixture
def mocked_fetchable_git_repo_main():
    """Gross fixture for explicit branch name -- TODO: fix using parameterization (?)"""
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        repo = mock.Mock()
        reference = MockBranch("main")
        repo.references = [reference]

        def create_remote(o, r):
            origin = mock.Mock()
            origin.refs = {"main": mock.Mock()}
            return origin

        repo.create_remote = create_remote
        repo.heads = {"main": mock.Mock()}

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


@pytest.mark.asyncio
async def test_launch_git_version_branch_set(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    mock_with_run_info = await _launch._launch(
        api=api, uri="https://foo:bar@github.com/FooTest/Foo.git", version="foobar"
    )

    assert "foobar" in str(mock_with_run_info.args[0].git_version)


@pytest.mark.asyncio
async def test_launch_git_version_default_master(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    mock_with_run_info = await _launch._launch(
        api=api,
        uri="https://foo:bar@github.com/FooTest/Foo.git",
    )

    assert "master" in str(mock_with_run_info.args[0].git_version)


@pytest.mark.asyncio
async def test_launch_git_version_default_main(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo_main,
    mock_load_backend,
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    mock_with_run_info = await _launch._launch(
        api=api,
        uri="https://foo:bar@github.com/FooTest/Foo.git",
    )

    assert "main" in str(mock_with_run_info.args[0].git_version)


@pytest.mark.asyncio
async def test_noop_builder(
    live_mock_server,
    test_settings,
    mocked_fetchable_git_repo_main,
    runner,
    monkeypatch,
):
    launch_config = {"builder": {"type": "noop"}, "registry": {"url": "test"}}
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    monkeypatch.setattr(
        wandb.sdk.launch.builder.build,
        "LAUNCH_CONFIG_FILE",
        "./config/wandb/launch-config.yaml",
    )

    with runner.isolated_filesystem():
        os.makedirs("./config/wandb")
        with open("./config/wandb/launch-config.yaml", "w") as f:
            json.dump(launch_config, f)

        kwargs = {
            "uri": "https://wandb.ai/mock_server_entity/test/runs/2",
            "api": api,
            "entity": "mock_server_entity",
            "project": "test",
            "synchronous": False,
        }
        expected = (
            "Attempted build with noop builder. Specify a builder in your launch config at ~/.config/wandb/launch-config.yaml.\n"
            "Note: Jobs sourced from git repos and code artifacts require a builder, while jobs sourced from Docker images do not.\n"
            "See https://docs.wandb.ai/guides/launch/create-job."
        )
        with pytest.raises(LaunchError, match=expected):
            await _launch._launch(**kwargs)
