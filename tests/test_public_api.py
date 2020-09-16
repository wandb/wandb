"""
test_wandb
----------------------------------

Tests for the `wandb.apis.PublicApi` module.
"""

import os
import json
import pytest
import platform

import wandb
from wandb import Api


@pytest.fixture
def api(runner):
    return Api()


def test_api_auto_login_no_tty(mocker):
    with pytest.raises(wandb.UsageError):
        Api()


def test_parse_project_path(api):
    e, p = api._parse_project_path("user/proj")
    assert e == "user"
    assert p == "proj"


def test_parse_project_path_proj(api, mock_server):
    e, p = api._parse_project_path("proj")
    assert e == "mock_server_entity"
    assert p == "proj"


def test_parse_path_simple(api):
    u, p, r = api._parse_path("user/proj/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_leading(api):
    u, p, r = api._parse_path("/user/proj/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_docker(api):
    u, p, r = api._parse_path("user/proj:run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_docker_proj(mock_server, api):
    u, p, r = api._parse_path("proj:run")
    assert u == "mock_server_entity"
    assert p == "proj"
    assert r == "run"


def test_parse_path_url(api):
    u, p, r = api._parse_path("user/proj/runs/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_user_proj(mock_server, api):
    u, p, r = api._parse_path("proj/run")
    assert u == "mock_server_entity"
    assert p == "proj"
    assert r == "run"


def test_parse_path_proj(mock_server, api):
    u, p, r = api._parse_path("proj")
    assert u == "mock_server_entity"
    assert p == "proj"
    assert r == "proj"


def test_run_from_path(mock_server, api):
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_retry(mock_server, api):
    mock_server.set_context("fail_graphql_times", 2)
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_history(mock_server, api):
    run = api.run("test/test/test")
    assert run.history(pandas=False)[0] == {'acc': 10, 'loss': 90}


def test_run_history_keys(mock_server, api):
    run = api.run("test/test/test")
    assert run.history(keys=["acc", "loss"], pandas=False) == [
           {"loss": 0, "acc": 100}, {"loss": 1, "acc": 0}]


def test_run_config(mock_server, api):
    run = api.run("test/test/test")
    assert run.config == {'epochs': 10}


def test_run_history_system(mock_server, api):
    run = api.run("test/test/test")
    assert run.history(stream="system", pandas=False) == [
        {'cpu': 10}, {'cpu': 20}, {'cpu': 30}]


def test_run_summary(mock_server, api):
    run = api.run("test/test/test")
    run.summary.update({"cool": 1000})
    res = json.loads(mock_server.ctx["graphql"][-1]["variables"]["summaryMetrics"])
    assert {"acc": 100, "loss": 0, "cool": 1000} == res


def test_run_create(mock_server, api):
    run = api.create_run(project="test")
    variables = {'entity': "mock_server_entity", 'name': run.id, 'project': 'test'}
    assert mock_server.ctx["graphql"][-1]["variables"] == variables


def test_run_update(mock_server, api):
    run = api.run("test/test/test")
    run.tags.append("test")
    run.config["foo"] = "bar"
    run.update()
    res = json.loads(mock_server.ctx["graphql"][-1]["variables"]["summaryMetrics"])
    assert {"acc": 100, "loss": 0} == res
    assert mock_server.ctx["graphql"][-2]["variables"]["entity"] == "test"


def test_run_files(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.files()[0]
        file.download()
        assert os.path.exists("weights.h5")
        raised = False
        try:
            file.download()
        except wandb.CommError:
            raised = True
        assert raised


def test_run_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert not os.path.exists("weights.h5")
        file.download()
        assert os.path.exists("weights.h5")


def test_runs_from_path(mock_server, api):
    runs = api.runs("test/test")
    assert len(runs) == 4
    list(runs)
    assert len(runs.objects) == 2
    assert runs[0].summary_metrics == {"acc": 100, "loss": 0}


def test_runs_from_path_index(mock_server, api):
    mock_server.set_context("page_times", 4)
    runs = api.runs("test/test")
    assert len(runs) == 4
    print(list(runs))
    assert runs[3]
    assert len(runs.objects) == 4


def test_projects(mock_server, api):
    projects = api.projects("test")
    # projects doesn't provide a length for now, so we iterate
    # them all to count
    count = 0
    for proj in projects:
        count += 1
    assert count == 2


def test_artifact_versions(runner, mock_server, api):
    versions = api.artifact_versions("dataset", "mnist")
    assert len(versions) == 2
    assert versions[0].name == "mnist:v0"
    assert versions[1].name == "mnist:v1"


def test_artifact_type(runner, mock_server, api):
    atype = api.artifact_type("dataset")
    assert atype.name == "dataset"
    col = atype.collection("mnist")
    assert col.name == "mnist"
    cols = atype.collections()
    assert cols[0].name == "mnist"


def test_artifact_types(runner, mock_server, api):
    atypes = api.artifact_types("dataset")

    raised = False
    try:
        assert len(atypes) == 2
    except ValueError:
        raised = True
    assert raised
    assert atypes[0].name == "dataset"


def test_artifact_get_path(runner, mock_server, api):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    assert art.type == "dataset"
    assert art.name == "mnist:v0"
    with runner.isolated_filesystem():
        path = art.get_path("digits.h5")
        res = path.download()
        path = os.path.join(os.path.expanduser("~"), ".cache", "wandb", "artifacts",
                            "obj", "md5", "4d", "e489e31c57834a21b8be7111dab613")
        assert res == path


def test_artifact_get_path_download(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.get_path("digits.h5").download(os.getcwd())
        assert os.path.exists("./digits.h5")
        assert path == os.path.join(os.getcwd(), "digits.h5")


def test_artifact_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.file()
        if platform.system() == "Windows":
            part = "mnist-v0"
        else:
            part = "mnist:v0"
        assert path == os.path.join(".", "artifacts", part, "digits.h5")


def test_artifact_download(runner, mock_server, api):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.download()
        if platform.system() == "Windows":
            part = "mnist-v0"
        else:
            part = "mnist:v0"
        assert path == os.path.join(".", "artifacts", part)


def test_artifact_run_used(runner, mock_server, api):
    run = api.run("test/test/test")
    arts = run.used_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "mnist:v0"


def test_artifact_run_logged(runner, mock_server, api):
    run = api.run("test/test/test")
    arts = run.logged_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "mnist:v0"


def test_artifact_manual_use(runner, mock_server, api):
    run = api.run("test/test/test")
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    run.use_artifact(art)
    assert True


def test_artifact_manual_log(runner, mock_server, api):
    run = api.run("test/test/test")
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    run.log_artifact(art)
    assert True


def test_artifact_manual_error(runner, mock_server, api):
    run = api.run("test/test/test")
    art = wandb.Artifact("test", type="dataset")
    with pytest.raises(wandb.CommError):
        run.log_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact(art)
    with pytest.raises(wandb.CommError):
        run.use_artifact("entity/project/mnist:v0")
    with pytest.raises(wandb.CommError):
        run.log_artifact("entity/project/mnist:v0")


@pytest.mark.skipif(platform.system() == "Windows",
                    reason="Verify is broken on Windows")
def test_artifact_verify(runner, mock_server, api):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    art.download()
    with pytest.raises(ValueError):
        art.verify()


def test_sweep(runner, mock_server, api):
    sweep = api.sweep("test/test/test")
    assert sweep.entity == "test"
    assert sweep.best_run().name == "beast-bug-33"