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
from .api_mocks import *
from click.testing import CliRunner
import git
from .utils import git_repo

import wandb
from wandb import Api
from six import StringIO
api = Api()


def test_run_from_path(request_mocker, query_run_v2):
    run_mock = query_run_v2(request_mocker)
    run = api.run("test/test/test")
    assert run.summary_metrics == {"acc": 100, "loss": 0}


def test_run_history(request_mocker, query_run_v2):
    run_mock = query_run_v2(request_mocker)
    run = api.run("test/test/test")
    assert run.history(pandas=False)[0] == {'acc': 10, 'loss': 90}


def test_run_config(request_mocker, query_run_v2):
    run_mock = query_run_v2(request_mocker)
    run = api.run("test/test/test")
    assert run.config == {'epochs': 10}


def test_run_history_system(request_mocker, query_run_v2):
    run_mock = query_run_v2(request_mocker)
    run = api.run("test/test/test")
    assert run.history(stream="system", pandas=False) == [
        {'cpu': 10}, {'cpu': 20}, {'cpu': 30}]


def test_run_summary(request_mocker, query_run_v2, upsert_run):
    run_mock = query_run_v2(request_mocker)
    update_mock = upsert_run(request_mocker)
    run = api.run("test/test/test")
    run.summary.update({"cool": 1000})
    assert update_mock.called


def test_runs_from_path(request_mocker, query_runs_v2):
    runs_mock = query_runs_v2(request_mocker)
    runs = api.runs("test/test")
    assert len(runs) == 4
    assert len(runs.runs) == 2
    assert runs[0].summary_metrics == {"acc": 100, "loss": 0}


def test_runs_from_path_index(mocker, request_mocker, query_runs_v2):
    runs_mock = query_runs_v2(request_mocker)
    runs = api.runs("test/test")
    assert len(runs) == 4
    run_mock = mocker.patch.object(runs, 'more')
    run_mock.side_effect = [True, False]
    assert runs[3]
    assert len(runs.runs) == 4
