#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_wandb
----------------------------------

Tests for the `wandb.Api` module.
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
from wandb import api as wandb_api
from six import StringIO
api = wandb_api.Api(load_settings=False,
                    retry_timedelta=datetime.timedelta(0, 0, 50))


def test_projects_success(request_mocker, query_projects):
    query_projects(request_mocker)
    res = api.list_projects()
    assert len(res) == 3


def test_projects_failure(request_mocker, query_projects):
    query_projects(request_mocker, status_code=400, error="Bummer")
    with pytest.raises(wandb.Error):
        api.list_projects()


def test_project_download_urls(request_mocker, query_project):
    query_project(request_mocker)
    res = api.download_urls("test")
    assert res == {
        'weights.h5': {'name': 'weights.h5', 'md5': 'fakemd5', 'url': 'https://weights.url'},
        'model.json': {'name': 'model.json', 'md5': 'mZFLkyvTelC5g8XnyQrpOw==', 'url': 'https://model.url'}
    }


def test_project_upload_urls(request_mocker, query_project):
    query_project(request_mocker)
    bucket_id, res = api.upload_urls(
        "test", files=["weights.h5", "model.json"])
    assert bucket_id == 'test1234'
    assert res == {
        'weights.h5': {'name': 'weights.h5', 'url': 'https://weights.url', 'md5': 'fakemd5'},
        'model.json': {'name': 'model.json', 'url': 'https://model.url', 'md5': 'mZFLkyvTelC5g8XnyQrpOw=='}
    }


def test_download_success(request_mocker, download_url):
    download_url(request_mocker)
    res = api.download_file("https://weights.url")
    assert res[1].status_code == 200


def test_download_failure(request_mocker, download_url):
    download_url(request_mocker, status_code=500)
    with pytest.raises(wandb.Error):
        api.download_file("https://weights.url")


def test_parse_slug():
    project, run = api.parse_slug("foo/bar")
    assert project == "foo"
    assert run == "bar"
    project, run = api.parse_slug("foo", project="bar")
    assert project == "bar"
    assert run == "foo"


def test_pull_success(request_mocker, download_url, query_project):
    query_project(request_mocker)
    download_url(request_mocker)
    with CliRunner().isolated_filesystem():
        os.mkdir('.wandb')
        os.mkdir('wandb')
        res = api.pull("test/test")
    assert res[0].status_code == 200


def test_pull_existing_file(request_mocker, mocker, download_url, query_project):
    query_project(request_mocker)
    download_url(request_mocker)
    with CliRunner().isolated_filesystem():
        os.mkdir('.wandb')
        os.mkdir('wandb')
        with open("model.json", "w") as f:
            f.write("{}")
        mocked = mocker.patch.object(
            api, "download_file", return_value=(100, mocker.MagicMock()))
        api.pull("test/test")
        mocked.assert_called_once_with("https://weights.url")


def test_push_success(request_mocker, upload_url, query_project, upsert_run):
    query_project(request_mocker)
    upload_url(request_mocker)
    update_mock = upsert_run(request_mocker)
    with CliRunner().isolated_filesystem():
        res = os.mkdir("wandb")
        # TODO: need this for my mock to work
        api = wandb_api.Api(load_settings=False)
        with open("wandb/latest.yaml", "w") as f:
            f.write(yaml.dump({'wandb_version': 1, 'test': {
                    'value': 'success', 'desc': 'My life'}}))
        with open("weights.h5", "w") as f:
            f.write("weight")
        with open("model.json", "w") as f:
            f.write("model")
        res = api.push("test/test", ["weights.h5", "model.json"])
    assert res[0].status_code == 200


def test_push_git_success(request_mocker, mocker, upload_url, query_project, upsert_run):
    query_project(request_mocker)
    upload_url(request_mocker)
    update_mock = upsert_run(request_mocker)
    with CliRunner().isolated_filesystem():
        res = os.mkdir("wandb")
        with open("wandb/latest.yaml", "w") as f:
            f.write(yaml.dump({'wandb_version': 1, 'test': {
                    'value': 'success', 'desc': 'My life'}}))
        with open("weights.h5", "w") as f:
            f.write("weight")
        with open("model.json", "w") as f:
            f.write("model")
        r = git.Repo.init(".")
        r.index.add(["model.json"])
        r.index.commit("initial commit")
        api = wandb_api.Api(load_settings=False,
                            default_settings={'git_tag': True})
        mock = mocker.patch.object(api.git, "push")
        res = api.push("test/test", ["weights.h5", "model.json"])
    assert res[0].status_code == 200
    mock.assert_called_once_with("test")


def test_push_no_project(request_mocker, upload_url, query_project):
    query_project(request_mocker)
    upload_url(request_mocker)
    with pytest.raises(wandb.Error):
        res = api.push("test", "weights.json")


def test_upload_success(request_mocker, upload_url):
    upload_url(request_mocker)
    res = api.upload_file(
        "https://weights.url", open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))
    assert res.status_code == 200


def test_upload_failure(request_mocker, upload_url):
    upload_url(request_mocker, status_code=500)
    with pytest.raises(wandb.Error):
        api.upload_file("https://weights.url",
                        open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))


def test_upload_failure_resumable(request_mocker, upload_url):
    upload_url(request_mocker, status_code=500)
    request_mocker.register_uri('PUT', "https://weights.url", request_headers={
                                'Content-Length': '0'}, headers={'Range': "0-10"}, status_code=308)
    request_mocker.register_uri('PUT', "https://weights.url",
                                request_headers={'Content-Range': 'bytes 10-51373/51373'})
    res = api.upload_file(
        "https://weights.url", open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))
    assert res.status_code == 200


def test_settings(mocker):
    api._settings = None
    parser = mocker.patch.object(api, "_settings_parser")
    parser.sections.return_value = ["default"]
    parser.options.return_value = ["project", "entity"]
    parser.get.side_effect = ["test_model", "test_entity"]
    assert api.settings() == {
        'base_url': 'https://api.wandb.ai',
        'entity': 'test_entity',
        'project': 'test_model',
        'section': 'default',
        'run': 'latest',
        'git_remote': 'origin',
        'git_tag': False
    }


def test_default_settings():
    assert wandb_api.Api({'base_url': 'http://localhost'}, load_settings=False).settings() == {
        'base_url': 'http://localhost',
        'entity': 'models',
        'section': 'default',
        'run': 'latest',
        'git_remote': 'origin',
        'git_tag': False,
        'project': None,
    }


def test_init(git_repo, upsert_run, request_mocker):
    upsert_run(request_mocker)
    os.environ['WANDB_RUN_STORAGE_ID'] = 'abc'
    os.environ['WANDB_MODE'] = 'run'
    run = wandb.init()
    assert run.mode == "run"
    # TODO: make a fixture?  This is gross
    del os.environ['WANDB_MODE']
    del os.environ['WANDB_INITED']
    del os.environ['WANDB_RUN_STORAGE_ID']
    del os.environ['WANDB_RUN_ID']
    del os.environ['WANDB_RUN_DIR']
