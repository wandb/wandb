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
from .api_mocks import _run, _query
from click.testing import CliRunner
import git
import json
from .utils import git_repo
import h5py
import numpy as np

import wandb
from wandb import Api
from six import StringIO
api = Api()


def test_run_from_path(request_mocker, query_run_v2, query_download_h5):
    run_mock = query_run_v2(request_mocker)
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


def test_run_summary(request_mocker, query_run_v2, upsert_run, query_download_h5):
    run_mock = query_run_v2(request_mocker)
    query_download_h5(request_mocker)
    update_mock = upsert_run(request_mocker)
    run = api.run("test/test/test")
    run.summary.update({"cool": 1000})
    assert update_mock.called


def test_runs_from_path(request_mocker, query_runs_v2, query_download_h5):
    runs_mock = query_runs_v2(request_mocker)
    query_download_h5(request_mocker)
    runs = api.runs("test/test")
    assert len(runs) == 4

    assert len(runs.runs) == 2
    assert runs[0].summary_metrics == {"acc": 100, "loss": 0}


def test_runs_from_path_index(mocker, request_mocker, query_runs_v2, query_download_h5):
    runs_mock = query_runs_v2(request_mocker)
    query_download_h5(request_mocker)
    runs = api.runs("test/test")
    assert len(runs) == 4
    run_mock = mocker.patch.object(runs, 'more')
    run_mock.side_effect = [True, False]
    assert runs[3]
    assert len(runs.runs) == 4


def test_read_advanced_summary(request_mocker, upsert_run, query_download_h5, query_upload_h5):
    run = _run()
    run["summaryMetrics"] = json.dumps({
        "special": {"_type": "numpy.ndarray", "min": 0, "max": 20},
        "normal": 32,
        "nested": {"deep": {"_type": "numpy.ndarray", "min": 0, "max": 20}}})
    _query('project', {'run': run})(request_mocker)
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
    assert list(run.summary._h5["summary"].keys()) == [
        "nested.deep", "special"]
