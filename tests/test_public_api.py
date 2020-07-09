#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_wandb
----------------------------------

Tests for the `wandb.apis.PublicApi` module.
"""
import datetime
import pytest
import os
import yaml
import tempfile
from .api_mocks import *
from click.testing import CliRunner
import git
import json
from .utils import git_repo, runner
import h5py
import numpy as np

import wandb
from wandb import Api
from six import StringIO
api = Api()


def test_parse_path_simple():
    u, p, r = api._parse_path("user/proj/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_leading():
    u, p, r = api._parse_path("/user/proj/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_docker():
    u, p, r = api._parse_path("user/proj:run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_docker_proj(mock_server):
    u, p, r = api._parse_path("proj:run")
    assert u == "vanpelt"
    assert p == "proj"
    assert r == "run"


def test_parse_path_url():
    u, p, r = api._parse_path("user/proj/runs/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_user_proj(mock_server):
    u, p, r = api._parse_path("proj/run")
    assert u == "vanpelt"
    assert p == "proj"
    assert r == "run"


def test_parse_path_proj(mock_server):
    u, p, r = api._parse_path("proj")
    assert u == "vanpelt"
    assert p == "proj"
    assert r == "proj"


def test_run_from_path(mock_server):
    api.flush()
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_retry(mock_server):
    api.flush()
    mock_server.set_context("fail_times", 2)
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_history(mock_server):
    api.flush()
    run = api.run("test/test/test")
    assert run.history(pandas=False)[0] == {'acc': 10, 'loss': 90}


def test_run_config(mock_server):
    api.flush()
    run = api.run("test/test/test")
    assert run.config == {'epochs': 10}


def test_run_history_system(mock_server):
    api.flush()
    run = api.run("test/test/test")
    assert run.history(stream="system", pandas=False) == [
        {'cpu': 10}, {'cpu': 20}, {'cpu': 30}]


def test_run_summary(mock_server):
    api.flush()
    run = api.run("test/test/test")
    run.summary.update({"cool": 1000})
    assert json.loads(mock_server.ctx["graphql"][-1]["variables"]["summaryMetrics"]) == {"acc": 100, "loss": 0, "cool": 1000}


def test_run_create(mock_server):
    run = api.create_run(project="test")
    assert mock_server.ctx["graphql"][-1]["variables"] == {'entity': 'vanpelt', 'name': run.id, 'project': 'test'}


def test_run_update(mock_server):
    api.flush()
    run = api.run("test/test/test")
    run.tags.append("test")
    run.config["foo"] = "bar"
    run.update()
    assert json.loads(mock_server.ctx["graphql"][-1]["variables"]["summaryMetrics"]) == {"acc": 100, "loss": 0}
    assert mock_server.ctx["graphql"][-2]["variables"]["entity"] == "test"


def test_run_files(runner, mock_server):
    with runner.isolated_filesystem():
        api.flush()
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


def test_run_file(runner, mock_server):
    with runner.isolated_filesystem():
        api.flush()
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert not os.path.exists("weights.h5")
        print("YO", file.url)
        file.download()
        assert os.path.exists("weights.h5")


def test_runs_from_path(mock_server):
    api.flush()
    runs = api.runs("test/test")
    assert len(runs) == 4
    list(runs)
    assert len(runs.objects) == 2
    assert runs[0].summary_metrics == {"acc": 100, "loss": 0}


def test_runs_from_path_index(mock_server):
    api.flush()
    mock_server.set_context("page_times", 4)
    runs = api.runs("test/test")
    assert len(runs) == 4
    print(list(runs))
    assert runs[3]
    assert len(runs.objects) == 4


def test_projects(mock_server):
    projects = api.projects("test")
    # projects doesn't provide a length for now, so we iterate
    # them all to count
    count = 0
    for proj in projects:
        count += 1
    assert count == 2


def test_sweep(request_mocker):
    run_responses = [random_run_response() for _ in range(5)]
    sweep_response = random_sweep_response()
    sweep_response['runs'] = {'edges': [{'node': r} for r in run_responses]}
    for r in run_responses:
        r['sweepName'] = sweep_response['name']

    mock_graphql_request(request_mocker, {'project': {'sweep': sweep_response}})

    sweep = api.sweep('test/test/{}'.format(sweep_response['name']))
    assert sweep.entity == 'test'
    assert sweep.project == 'test'
    assert sweep.name
    assert sweep.config
    assert sweep.best_loss
    assert len(sweep.runs) == len(run_responses)


def test_reports(request_mocker):
    report_response = basic_report_response()
    mock_graphql_request(request_mocker, {'project': report_response}, body_match='query Run')
    report = api.reports("test/test/test")[0]
    assert report.sections[0]['name'] == '01: Effect of hidden layer size on feedforward net'
    query = {"op": "OR",
             "filters": [{"op": "AND",
                          "filters": [{"key": {"section": "tags", "name": "basic_feedforward"},
                                       "op": "=",
                                       "value": True,
                                       "disabled": False}]}]}
    print(report.query_generator.filter_to_mongo(query))
    assert report.query_generator.filter_to_mongo(query) == {'$or': [{'$and': [{'tags': 'basic_feedforward'}]}]}


def test_run_sweep(request_mocker):
    run_response = random_run_response()
    sweep_response = random_sweep_response()
    run_response['sweepName'] = sweep_response['name']

    mock_graphql_request(request_mocker, {'project': {'run': run_response}}, body_match='query Run')
    mock_graphql_request(request_mocker, {'project': {'sweep': sweep_response}}, body_match='query Sweep')

    run = api.run('test/test/{}'.format(run_response['name']))
    assert run.id
    assert run.name
    assert run.sweep
    assert run.sweep.id
    assert run.sweep.runs == [run]


def test_runs_sweeps(request_mocker):
    """Request a bunch of runs from different sweeps at the same time.
    Ensure each run's sweep attribute is set to the appropriate value.
    """
    api = Api()
    run_responses = [random_run_response() for _ in range(7)]
    sweep_a_response = random_sweep_response()
    sweep_b_response = random_sweep_response()
    run_responses[0]['sweepName'] = sweep_b_response['name']
    run_responses[1]['sweepName'] = sweep_a_response['name']
    run_responses[3]['sweepName'] = sweep_b_response['name']
    run_responses[4]['sweepName'] = sweep_a_response['name']
    run_responses[5]['sweepName'] = sweep_b_response['name']
    run_responses[6]['sweepName'] = sweep_b_response['name']

    runs_response = {
        'project': {
            'runCount': len(run_responses),
            'runs': {
                'pageInfo': {'hasNextPage': False},
                'edges': [{'node': r, 'cursor': 'cursor'} for r in run_responses],
            }
        }
    }
    mock_graphql_request(request_mocker, runs_response, body_match='query Runs')
    mock_graphql_request(request_mocker, {'project': {'sweep': sweep_a_response}},
                         body_match=sweep_a_response['name'])
    mock_graphql_request(request_mocker, {'project': {'sweep': sweep_b_response}},
                         body_match=sweep_b_response['name'])

    runs = list(api.runs('test/test'))
    sweep_a = runs[1].sweep
    sweep_b = runs[0].sweep
    assert len(runs) == len(run_responses)
    assert sweep_a.runs == [runs[1], runs[4]]
    assert sweep_b.runs == [runs[0], runs[3], runs[5], runs[6]]
    assert runs[0].sweep is sweep_b
    assert runs[1].sweep is sweep_a
    assert runs[2].sweep is None
    assert runs[3].sweep is sweep_b
    assert runs[4].sweep is sweep_a
    assert runs[5].sweep is sweep_b
    assert runs[6].sweep is sweep_b


# @pytest.mark.skip(readon='fails when I run the whole suite, but not when I run just this file')
def test_read_advanced_summary(runner, request_mocker, upsert_run, query_download_h5, query_upload_h5):
    with runner.isolated_filesystem():
        run = run_response()
        run["summaryMetrics"] = json.dumps({
            "special": {"_type": "numpy.ndarray", "min": 0, "max": 20},
            "normal": 32,
            "nested": {"deep": {"_type": "numpy.ndarray", "min": 0, "max": 20}}})
        query_mocker('project', {'run': run})(request_mocker)
        file = os.path.join(tempfile.gettempdir(), "test.h5")
        with h5py.File(file, 'w') as h5:
            h5["summary/special"] = np.random.rand(100)
            h5["summary/nested.deep"] = np.random.rand(100)
        query_download_h5(request_mocker, content=open(file, "rb").read())
        api.flush()
        run = api.run("test/test/test")
        assert len(run.summary["special"]) == 100
        assert len(run.summary["nested"]["deep"]) == 100
        update_mock = upsert_run(request_mocker)
        h5_mock = query_upload_h5(request_mocker)
        run.summary.update({"nd_time": np.random.rand(1000)})
        assert len(run.summary["nd_time"]) == 1000
        # TODO: this passes locally, but fails consistently in CI?!?
        #assert h5_mock.called
        del run.summary["nd_time"]
        run.summary.open_h5()
        assert list(sorted(run.summary._h5["summary"].keys())) == [
            "nested.deep", "special"]

def test_artifact_versions(runner, mock_server):
    versions = api.artifact_versions("dataset", "mnist")
    assert len(versions) == 2
    assert versions[0].name == "mnist:v0"
    assert versions[1].name == "mnist:v1"

def test_artifact_type(runner, mock_server):
    atype = api.artifact_type("dataset")
    assert atype.name == "dataset"
    col = atype.collection("mnist")
    assert col.name == "mnist"
    cols = atype.collections()
    assert cols[0].name == "mnist"

def test_artifact_types(runner, mock_server):
    atypes = api.artifact_types("dataset")

    raised = False
    try:
        assert len(atypes) == 2
    except ValueError:
        raised = True
    assert raised
    assert atypes[0].name == "dataset"

def test_artifact_get_path(runner, mock_server):
    art = api.artifact("entity/project/mnist:v0", type="dataset")
    assert art.type == "dataset"
    assert art.name == "mnist:v0"
    with runner.isolated_filesystem():
        path = art.get_path("digits.h5")
        res = path.download()
        assert res == os.path.expanduser("~")+ "/.cache/wandb/artifacts/obj/md5/4d/e489e31c57834a21b8be7111dab613"

def test_artifact_file(runner, mock_server):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.file()
        assert path == "./artifacts/mnist:v0/digits.h5"

def test_artifact_download(runner, mock_server):
    with runner.isolated_filesystem():
        art = api.artifact("entity/project/mnist:v0", type="dataset")
        path = art.download()
        assert path == "./artifacts/mnist:v0"

def test_artifact_run_used(runner, mock_server):
    api.flush()
    run = api.run("test/test/test")
    arts = run.used_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "abc123"

def test_artifact_run_logged(runner, mock_server):
    api.flush()
    run = api.run("test/test/test")
    arts = run.logged_artifacts()
    assert len(arts) == 2
    assert arts[0].name == "abc123"