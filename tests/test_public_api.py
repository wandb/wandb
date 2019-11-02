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


def test_parse_path_docker_proj():
    u, p, r = api._parse_path("proj:run")
    assert u == None
    assert p == "proj"
    assert r == "run"


def test_parse_path_url():
    u, p, r = api._parse_path("user/proj/runs/run")
    assert u == "user"
    assert p == "proj"
    assert r == "run"


def test_parse_path_user_proj():
    u, p, r = api._parse_path("user/proj")
    assert u == "user"
    assert p == "proj"
    assert r == "proj"


def test_parse_path_proj():
    u, p, r = api._parse_path("proj")
    assert u == None
    assert p == "proj"
    assert r == "proj"


def test_run_from_path(request_mocker, query_run_v2, query_download_h5):
    run_mock = query_run_v2(request_mocker)
    query_download_h5(request_mocker)
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_retry(request_mocker, query_run_v2, query_download_h5):
    run_mock = query_run_v2(request_mocker, status_code=500, attempts=3)
    query_download_h5(request_mocker)
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_history(request_mocker, query_run_v2, query_download_h5):
    run_mock = query_run_v2(request_mocker)
    query_download_h5(request_mocker)
    run = api.run("test/test/test")
    assert run.history(pandas=False)[0] == {'acc': 10, 'loss': 90}


def test_run_config(request_mocker, query_run_v2, query_download_h5):
    run_mock = query_run_v2(request_mocker)
    query_download_h5(request_mocker)
    run = api.run("test/test/test")
    assert run.config == {'epochs': 10}


def test_run_history_system(request_mocker, query_run_v2, query_download_h5):
    run_mock = query_run_v2(request_mocker)
    query_download_h5(request_mocker)
    run = api.run("test/test/test")
    assert run.history(stream="system", pandas=False) == [
        {'cpu': 10}, {'cpu': 20}, {'cpu': 30}]


def test_run_summary(request_mocker, query_run_v2, upsert_run, query_download_h5, query_upload_h5):
    run_mock = query_run_v2(request_mocker)
    query_download_h5(request_mocker)
    # TODO: this likely shouldn't need to be mocked
    query_upload_h5(request_mocker)
    update_mock = upsert_run(request_mocker)
    run = api.run("test/test/test")
    run.summary.update({"cool": 1000})
    assert update_mock.called


def test_run_create(request_mocker, query_run_v2, upsert_run, query_download_h5):
    run_mock = query_run_v2(request_mocker)
    query_download_h5(request_mocker)
    update_mock = upsert_run(request_mocker)
    run = api.create_run(project="test")
    assert update_mock.called


def test_run_update(request_mocker, query_run_v2, upsert_run, query_download_h5, query_upload_h5):
    query_download_h5(request_mocker)
    # TODO: this likely shouldn't need to be mocked
    query_upload_h5(request_mocker)
    update_mock = upsert_run(request_mocker)
    run_mock = query_run_v2(request_mocker)
    run = api.run("test/test/test")
    run.tags.append("test")
    run.config["foo"] = "bar"
    run.update()
    assert update_mock.called


def test_run_files(runner, request_mocker, query_run_v2, query_run_files):
    with runner.isolated_filesystem():
        run_mock = query_run_v2(request_mocker)
        query_run_files(request_mocker)
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


def test_run_file(runner, request_mocker, query_run_v2, query_run_files):
    with runner.isolated_filesystem():
        run_mock = query_run_v2(request_mocker)
        query_run_files(request_mocker)
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert not os.path.exists("weights.h5")
        file.download()
        assert os.path.exists("weights.h5")


def test_runs_from_path(request_mocker, query_runs_v2, query_download_h5):
    runs_mock = query_runs_v2(request_mocker)
    query_download_h5(request_mocker)
    runs = api.runs("test/test")
    assert len(runs) == 4

    assert len(runs.objects) == 2
    assert runs[0].summary_metrics == {"acc": 100, "loss": 0}


def test_runs_from_path_index(mocker, request_mocker, query_runs_v2, query_download_h5):
    runs_mock = query_runs_v2(request_mocker)
    query_download_h5(request_mocker)
    runs = api.runs("test/test")
    assert len(runs) == 4
    run_mock = mocker.patch('wandb.apis.public.Runs.more')
    run_mock.side_effect = [True, False]
    assert runs[3]
    assert len(runs.objects) == 4


def test_projects(mocker, request_mocker, query_projects_v2):
    runs_mock = query_projects_v2(request_mocker)
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
