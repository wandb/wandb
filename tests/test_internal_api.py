#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_wandb
----------------------------------

Tests for the `wandb.InternalApi` module.
"""
import datetime
import pytest
import os
import yaml
from .api_mocks import *
from click.testing import CliRunner
import git
from .utils import git_repo

import requests
import wandb
from wandb.apis import internal
from six import StringIO
api = internal.Api(load_settings=False,
                   retry_timedelta=datetime.timedelta(0, 0, 50))


def test_projects_success(request_mocker, query_projects):
    query_projects(request_mocker)
    res = api.list_projects()
    assert len(res) == 3


def test_projects_failure(request_mocker, query_projects):
    query_projects(request_mocker, status_code=400,
                   error=[{'message': "Bummer"}])
    with pytest.raises(wandb.Error):
        api.list_projects()


def test_project_download_urls(request_mocker, query_project):
    query_project(request_mocker)
    res = api.download_urls("test")
    assert res == {
        'weights.h5': {'name': 'weights.h5', 'mimetype': '', 'sizeBytes': "100", 'md5': 'fakemd5', 'updatedAt': None, 'url': 'https://weights.url'},
        'model.json': {'name': 'model.json', 'mimetype': 'application/json', 'sizeBytes': "1000", 'md5': 'mZFLkyvTelC5g8XnyQrpOw==', 'updatedAt': None, 'url': 'https://model.url'}
    }


def test_project_upload_urls(request_mocker, query_project):
    query_project(request_mocker)
    bucket_id, res = api.upload_urls(
        "test", files=["weights.h5", "model.json"])
    assert bucket_id == 'test1234'
    assert res == {
        'weights.h5': {'name': 'weights.h5', 'mimetype': '', 'sizeBytes': "100", 'url': 'https://weights.url', 'updatedAt': None, 'md5': 'fakemd5'},
        'model.json': {'name': 'model.json', 'mimetype': 'application/json', 'sizeBytes': "1000", 'url': 'https://model.url', 'updatedAt': None, 'md5': 'mZFLkyvTelC5g8XnyQrpOw=='}
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
        api = internal.Api(load_settings=False)
        with open("wandb/latest.yaml", "w") as f:
            f.write(yaml.dump({'wandb_version': 1, 'test': {
                    'value': 'success', 'desc': 'My life'}}))
        with open("weights.h5", "w") as f:
            f.write("weight")
        with open("model.json", "w") as f:
            f.write("model")
        res = api.push(["weights.h5", "model.json"],
                       entity='test', project='test')
    assert res[0].status_code == 200


def test_push_no_project(request_mocker, upload_url, query_project):
    query_project(request_mocker)
    upload_url(request_mocker)
    del os.environ["WANDB_PROJECT"]
    with pytest.raises(wandb.Error):
        api = internal.Api(load_settings=False)
        print("WTF", api.settings("project"))
        res = api.push(["weights.json"], entity='test')


def test_upload_success(request_mocker, upload_url):
    upload_url(request_mocker)
    res = api.upload_file(
        "https://weights.url", open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))
    assert res.status_code == 200


def test_upload_failure(request_mocker, upload_url):
    upload_url(request_mocker, status_code=400)
    with pytest.raises(requests.exceptions.HTTPError):
        api.upload_file("https://weights.url",
                        open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))


def test_upload_failure_resumable(request_mocker, upload_url):
    upload_url(request_mocker)
    request_mocker.register_uri('PUT', "https://weights.url", request_headers={
                                'Content-Length': '0'}, headers={}, status_code=308)
    request_mocker.register_uri('PUT', "https://weights.url", request_headers={
                                'Content-Length': '0'}, headers={'Range': "0-10"}, status_code=308)
    request_mocker.register_uri('PUT', "https://weights.url",
                                request_headers={'Content-Range': 'bytes 10-51373/51373'})
    res = api.upload_file(
        "https://weights.url", open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))
    assert res.status_code == 200


def test_upsert_run_defaults(request_mocker, mocker, upsert_run):
    update_mock = upsert_run(request_mocker)
    res = api.upsert_run(project="new-test")
    print('RES: %s', res)
    # We should have set the project and entity in api settings
    assert api.settings('project') == 'new-project'
    assert api.settings('entity') == 'bagsy'


def test_settings(mocker):
    os.environ.pop('WANDB_ENTITY', None)
    os.environ.pop('WANDB_PROJECT', None)
    api._settings = None
    parser = mocker.patch.object(api, "settings_parser")
    parser.sections.return_value = ["default"]
    parser.options.return_value = ["project", "entity", "ignore_globs"]
    parser.get.side_effect = ["test_model",
                              "test_entity", "diff.patch,*.secure"]
    assert api.settings() == {
        'base_url': 'https://api.wandb.ai',
        'entity': 'test_entity',
        'project': 'test_model',
        'section': 'default',
        'run': 'latest',
        'ignore_globs': ["diff.patch", "*.secure"],
        'git_remote': 'origin',
    }


def test_default_settings():
    os.environ.pop('WANDB_ENTITY', None)
    os.environ.pop('WANDB_PROJECT', None)
    assert internal.Api({'base_url': 'http://localhost'}, load_settings=False).settings() == {
        'base_url': 'http://localhost',
        'entity': None,
        'section': 'default',
        'run': 'latest',
        'ignore_globs': [],
        'git_remote': 'origin',
        'project': None,
    }


def test_dynamic_settings():
    assert internal.Api({}).dynamic_settings == {
        'heartbeat_seconds': 30, 'system_sample_seconds': 2, 'system_samples': 15}


@pytest.mark.skip('This tries to upsert run and fails')
def test_init(git_repo, upsert_run, request_mocker):
    upsert_run(request_mocker)
    os.environ['WANDB_RUN_STORAGE_ID'] = 'abc'
    os.environ['WANDB_MODE'] = 'run'
    run = wandb.init()
    assert run.mode == "run"
    wandb.reset_env()
