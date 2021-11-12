import json
import os
from wandb.apis import PublicApi
from unittest.mock import MagicMock
from wandb.sdk.launch.agent.agent import LaunchAgent
from wandb.sdk.launch.docker import pull_docker_image

try:
    from unittest import mock
except ImportError:  # TODO: this is only for python2
    import mock
import sys

import wandb
import wandb.util as util
import wandb.sdk.launch.launch as launch
from wandb.sdk.launch.launch_add import launch_add
import wandb.sdk.launch._project_spec as _project_spec
from wandb.sdk.launch.utils import (
    PROJECT_DOCKER_ARGS,
    PROJECT_SYNCHRONOUS,
)

from ..utils import fixture_open, notebook_path

import pytest


@pytest.fixture
def mocked_fetchable_git_repo():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        return mock.Mock()

    m.Repo.init = mock.Mock(side_effect=populate_dst_dir)
    with mock.patch.dict("sys.modules", git=m):
        yield m


@pytest.fixture
def mocked_fetchable_git_repo_ipython():
    m = mock.Mock()

    def populate_dst_dir(dst_dir):
        with open(os.path.join(dst_dir, "one_cell.ipynb"), "w") as f:
            f.write(open(notebook_path("one_cell.ipynb"), "r").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("test")
        return mock.Mock()

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

    with mock.patch("wandb.sdk.launch.launch.loader.load_backend") as mock_load_backend:
        m = mock.Mock(side_effect=side_effect)
        m.run = mock.Mock(side_effect=side_effect)
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


def check_project_spec(
    project_spec, api, uri, project=None, entity=None, config=None, parameters=None,
):
    assert project_spec.uri == uri
    expected_project = project or uri.split("/")[4]
    assert project_spec.target_project == expected_project
    expected_target_entity = entity or api.default_entity
    assert project_spec.target_entity == expected_target_entity
    if (
        config
        and config.get("config")
        and config["config"].get("overrides")
        and config["config"]["overrides"].get("run_config")
    ):
        assert (
            project_spec.override_config == config["config"]["overrides"]["run_config"]
        )

    with open(os.path.join(project_spec.project_dir, "patch.txt"), "r") as fp:
        contents = fp.read()
        assert contents == "testing"


def check_backend_config(config, expected_backend_config):
    for key, item in config.items():
        if key not in [PROJECT_DOCKER_ARGS, PROJECT_SYNCHRONOUS]:
            assert item == expected_backend_config[key]


def check_mock_run_info(mock_with_run_info, expected_config, kwargs):
    for arg in mock_with_run_info.args:
        if isinstance(arg, _project_spec.LaunchProject):
            check_project_spec(arg, **kwargs)
        if isinstance(arg, dict):
            check_backend_config(arg, expected_config)
    for arg in mock_with_run_info.kwargs.items():
        if isinstance(arg, _project_spec.LaunchProject):
            check_project_spec(arg, **kwargs)
        if isinstance(arg, dict):
            check_backend_config(arg, expected_config)


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions < 3.5",
)
def test_launch_base_case(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend
):

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    expected_config = {}
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
    }
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_config, kwargs)


def test_launch_add_base(live_mock_server):
    queuedJob = launch_add("https://wandb.ai/mock_server_entity/tests/runs/1")
    assert queuedJob._run_queue_item_id == "1"


@pytest.mark.skipif(
    sys.version_info < (3, 5),
    reason="wandb launch is not available for python versions <3.5",
)
def test_launch_specified_project(
    live_mock_server, test_settings, mocked_fetchable_git_repo, mock_load_backend,
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
    expected_config = {}
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_config, kwargs)


def test_launch_unowned_project(
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
    expected_config = {}
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_config, kwargs)


def test_launch_run_config_in_spec(
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
        "config": {"overrides": {"run_config": {"epochs": 3}}},
    }

    expected_runner_config = {}
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_runner_config, kwargs)


def test_launch_args_supersede_config_vals(
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
        "config": {
            "project": "not-this-project",
            "overrides": {
                "run_config": {"epochs": 3},
                "args": ["--epochs=2", "--heavy"],
            },
        },
        "parameters": {"epochs": 5},
    }
    input_kwargs = kwargs.copy()
    input_kwargs["parameters"] = ["epochs", 5]
    mock_with_run_info = launch.run(**kwargs)
    for arg in mock_with_run_info.args:
        if isinstance(arg, _project_spec.LaunchProject):
            assert arg.override_args["epochs"] == 5
            assert arg.override_config.get("epochs") is None
            assert arg.target_project == "new_test_project"


def test_run_in_launch_context_with_config(runner, live_mock_server, test_settings):
    with runner.isolated_filesystem():
        path = _project_spec.DEFAULT_LAUNCH_METADATA_PATH
        with open(path, "w") as fp:
            json.dump({"overrides": {"run_config": {"epochs": 10}}}, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()


def test_run_in_launch_context_with_artifact_string_no_used_as(
    runner, live_mock_server, test_settings
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
    overrides = {
        "overrides": {"run_config": {"epochs": 10}, "artifacts": {"old_name:v0": arti}},
    }
    with runner.isolated_filesystem():
        path = _project_spec.DEFAULT_LAUNCH_METADATA_PATH
        with open(path, "w") as fp:
            json.dump(overrides, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        arti_inst = run.use_artifact("old_name:v0")
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert arti_inst.name == "test:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "old_name:v0"


def test_run_in_launch_context_with_artifact_unique(
    runner, live_mock_server, test_settings
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
    overrides = {
        "overrides": {
            "run_config": {"epochs": 10},
            "artifacts": {"old_name:latest": arti},
        },
    }
    with runner.isolated_filesystem():
        path = _project_spec.DEFAULT_LAUNCH_METADATA_PATH
        with open(path, "w") as fp:
            json.dump(overrides, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        arti_inst = run.use_artifact("old_name:v0")
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert arti_inst.name == "test:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "old_name:v0"


def test_run_in_launch_context_with_artifact_project_entity_string_no_used_as(
    runner, live_mock_server, test_settings
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
    overrides = {
        "overrides": {"run_config": {"epochs": 10}, "artifacts": {"old_name:v0": arti}},
    }
    with runner.isolated_filesystem():
        path = _project_spec.DEFAULT_LAUNCH_METADATA_PATH
        with open(path, "w") as fp:
            json.dump(overrides, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        arti_inst = run.use_artifact("test/test/old_name:v0")
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert arti_inst.name == "test:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "test/test/old_name:v0"


def test_launch_code_artifact(
    runner, live_mock_server, test_settings, monkeypatch, mock_load_backend
):
    def download_func(dst_dir):
        with open(os.path.join(dst_dir, "train.py"), "w") as f:
            f.write(fixture_open("train.py").read())
        with open(os.path.join(dst_dir, "requirements.txt"), "w") as f:
            f.write(fixture_open("requirements.txt").read())
        with open(os.path.join(dst_dir, "patch.txt"), "w") as f:
            f.write("testing")

    run_with_artifacts = mock.MagicMock()
    code_artifact = mock.MagicMock()
    code_artifact.type = "code"
    code_artifact.download = download_func

    run_with_artifacts.logged_artifacts.return_value = [code_artifact]
    monkeypatch.setattr(
        wandb.PublicApi, "run", lambda *arg, **kwargs: run_with_artifacts
    )

    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    expected_config = {}
    uri = "https://wandb.ai/mock_server_entity/test/runs/1"
    kwargs = {
        "uri": uri,
        "api": api,
        "entity": "mock_server_entity",
        "project": "test",
    }
    mock_with_run_info = launch.run(**kwargs)
    check_mock_run_info(mock_with_run_info, expected_config, kwargs)


def test_run_in_launch_context_with_artifact_string_used_as_config(
    runner, live_mock_server, test_settings
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
    overrides = {
        "overrides": {"run_config": {"epochs": 10}, "artifacts": {"dataset": arti}},
    }
    with runner.isolated_filesystem():
        path = _project_spec.DEFAULT_LAUNCH_METADATA_PATH
        with open(path, "w") as fp:
            json.dump(overrides, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        arti_inst = run.use_artifact("old_name:latest", use_as="dataset")
        run.config.dataset = arti_inst
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert arti_inst.name == "test:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "dataset"


def test_run_in_launch_context_with_artifacts_api(
    runner, live_mock_server, test_settings, capsys
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
    overrides = {
        "overrides": {
            "run_config": {"epochs": 10},
            "artifacts": {"old_name:v0": arti},
        },
    }
    with runner.isolated_filesystem():
        path = _project_spec.DEFAULT_LAUNCH_METADATA_PATH
        with open(path, "w") as fp:
            json.dump(overrides, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        public_api = PublicApi()
        art = public_api.artifact("old_name:v0")
        arti_inst = run.use_artifact(art)
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert arti_inst.name == "old_name:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "old_name:v0"
        _, err = capsys.readouterr()
        assert (
            "Swapping artifacts does not support swapping artifacts used as an instance of"
            in err
        )


def test_run_in_launch_context_with_artifacts_no_match(
    runner, live_mock_server, test_settings
):
    live_mock_server.set_ctx({"swappable_artifacts": True})
    arti = {
        "name": "test/test/test:v0",
        "_version": "v0",
        "_type": "artifactVersion",
        "id": "QXJ0aWZhY3Q6NTI1MDk4",
    }
    overrides = {
        "overrides": {
            "run_config": {"epochs": 10},
            "artifacts": {"unfound_name": arti},
        },
    }
    with runner.isolated_filesystem():
        path = _project_spec.DEFAULT_LAUNCH_METADATA_PATH
        with open(path, "w") as fp:
            json.dump(overrides, fp)
        test_settings.launch = True
        test_settings.launch_config_path = path
        run = wandb.init(settings=test_settings, config={"epochs": 2, "lr": 0.004})
        arti_inst = run.use_artifact("old_name:v0")
        assert run.config.epochs == 10
        assert run.config.lr == 0.004
        run.finish()
        assert arti_inst.name == "old_name:v0"
        arti_info = live_mock_server.get_ctx()["used_artifact_info"]
        assert arti_info["used_name"] == "old_name:v0"


def test_push_to_runqueue(live_mock_server, test_settings):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    launch_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
    }
    api.push_to_run_queue("default", launch_spec)
    ctx = live_mock_server.get_ctx()
    assert len(ctx["run_queues"]["1"]) == 1


def test_push_to_default_runqueue_notexist(live_mock_server, test_settings):
    live_mock_server.set_ctx({"run_queues_return_default": False})
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    launch_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
    }
    api.push_to_run_queue("default", launch_spec)
    ctx = live_mock_server.get_ctx()
    assert len(ctx["run_queues"]["1"]) == 1


def test_push_to_runqueue_notfound(live_mock_server, test_settings, capsys):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    launch_spec = {
        "uri": "https://wandb.ai/mock_server_entity/test/runs/1",
        "entity": "mock_server_entity",
        "project": "test",
    }
    api.push_to_run_queue("not-found", launch_spec)
    ctx = live_mock_server.get_ctx()
    _, err = capsys.readouterr()
    assert len(ctx["run_queues"]["1"]) == 0
    assert "Unable to push to run queue not-found. Queue not found" in err


# this test includes building a docker container which can take some time.
# hence the timeout. caching should usually keep this under 30 seconds
@pytest.mark.timeout(320)
def test_launch_agent_runs(
    test_settings, live_mock_server, mocked_fetchable_git_repo, monkeypatch
):
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent.pop_from_queue",
        lambda c, queue: patched_pop_from_queue(c, queue),
    )
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    launch.create_and_run_agent(api, "mock_server_entity", "test_project")
    ctx = live_mock_server.get_ctx()
    assert ctx["num_popped"] == 1
    assert ctx["num_acked"] == 1
    assert len(ctx["launch_agents"].keys()) == 1


def test_launch_agent_instance(test_settings, live_mock_server):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    agent = LaunchAgent("mock_server_entity", "test_project", ["default"])
    ctx = live_mock_server.get_ctx()
    assert len(ctx["launch_agents"]) == 1
    assert agent._id == int(list(ctx["launch_agents"].keys())[0])

    get_agent_response = api.get_launch_agent(agent._id, agent.gorilla_supports_agents)
    assert get_agent_response["name"] == "test_agent"


def test_launch_agent_different_project_in_spec(
    test_settings,
    live_mock_server,
    mocked_fetchable_git_repo,
    monkeypatch,
    # mock_load_backend_agent,
    capsys,
):
    live_mock_server.set_ctx({"invalid_launch_spec_project": True})
    monkeypatch.setattr(
        "wandb.sdk.launch.agent.LaunchAgent.pop_from_queue",
        lambda c, queue: patched_pop_from_queue(c, queue),
    )
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    launch.create_and_run_agent(api, "mock_server_entity", "test_project")
    _, err = capsys.readouterr()

    ctx = live_mock_server.get_ctx()
    assert (
        "Launch agents only support sending runs to their own project and entity. This run will be sent to mock_server_entity/test_project"
        in err
    )


def test_agent_queues_notfound(test_settings, live_mock_server):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    try:
        launch.create_and_run_agent(
            api, "mock_server_entity", "test_project", ["nonexistent_queue"],
        )
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
    agent = LaunchAgent("mock_server_entity", "test_project", ["default"])
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
    assert get_agent_response["stopPolling"] == False


@pytest.mark.timeout(320)
def test_launch_notebook(
    live_mock_server, test_settings, mocked_fetchable_git_repo_ipython
):
    live_mock_server.set_ctx({"return_jupyter_in_run_info": True})
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    run = launch.run(
        "https://wandb.ai/mock_server_entity/test/runs/jupyter1",
        api,
        project="new-test",
    )
    assert str(run.get_status()) == "finished"


# this test includes building a docker container which can take some time.
# hence the timeout. caching should usually keep this under 30 seconds
@pytest.mark.timeout(320)
def test_launch_full_build_new_image(
    live_mock_server, test_settings, mocked_fetchable_git_repo
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )
    random_id = util.generate_id()
    run = launch.run(
        "https://wandb.ai/mock_server_entity/test/runs/1",
        api,
        project=f"new-test-{random_id}",
    )
    assert str(run.get_status()) == "finished"


@pytest.mark.timeout(320)
def test_launch_no_server_info(
    live_mock_server, test_settings, mocked_fetchable_git_repo
):
    api = wandb.sdk.internal.internal_api.Api(
        default_settings=test_settings, load_settings=False
    )

    api.get_run_info = MagicMock(
        return_value=None, side_effect=wandb.CommError("test comm error")
    )
    try:
        launch.run(
            "https://wandb.ai/mock_server_entity/test/runs/1", api, project=f"new-test",
        )
        assert False
    except wandb.errors.LaunchError as e:
        assert "Run info is invalid or doesn't exist" in str(e)


@pytest.mark.timeout(60)
def test_launch_metadata(live_mock_server, test_settings, mocked_fetchable_git_repo):
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
                    return [b"numpy==1.19.5\n"]
                elif self.url == "main2.py":
                    return [
                        b"import wandb\n",
                        b"import numpy\n",
                        b"print('ran server fetched code')\n",
                    ]

        return 200, MockedFileResponder(url)

    api.download_file = MagicMock(side_effect=mocked_file_download_request)
    run = launch.run(
        "https://wandb.ai/mock_server_entity/test/runs/1",
        api,
        project="test-another-new-project",
    )
    assert str(run.get_status()) == "finished"


def patched_pop_from_queue(self, queue):
    ups = self._api.pop_from_run_queue(
        queue, entity=self._entity, project=self._project
    )
    if not ups:
        raise KeyboardInterrupt
    return ups


def test_fail_pull_docker_image():
    try:
        pull_docker_image("not an image")
    except wandb.errors.LaunchError as e:
        assert "Docker server returned error" in str(e)
