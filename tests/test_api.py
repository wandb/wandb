#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_wandb
----------------------------------

Tests for the `wandb.Api` module.
"""
import pytest, os
from .api_mocks import *
from click.testing import CliRunner

import wandb
from six import StringIO
api = wandb.Api(load_config=False)

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
    res = api.upload_urls("test", files=["weights.h5", "model.json"])
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
    project, bucket = api.parse_slug("foo/bar")
    assert project == "foo"
    assert bucket == "bar"
    project, bucket = api.parse_slug("foo", project="bar")
    assert project == "bar"
    assert bucket == "foo"

def test_pull_success(request_mocker, download_url, query_project):
    query_project(request_mocker)
    download_url(request_mocker)
    with CliRunner().isolated_filesystem():
        res = api.pull("test/test")
    assert res[0].status_code == 200

def test_pull_existing_file(request_mocker, mocker, download_url, query_project):
    query_project(request_mocker)
    download_url(request_mocker)
    with CliRunner().isolated_filesystem():
        with open("model.json", "w") as f:
            f.write("{}")
        mocked = mocker.patch.object(api, "download_file", return_value=(100, mocker.MagicMock()))
        api.pull("test/test")
        mocked.assert_called_once_with("https://weights.url")

def test_push_success(request_mocker, upload_url, query_project):
    query_project(request_mocker)
    upload_url(request_mocker)
    with CliRunner().isolated_filesystem():
        with open("weights.h5", "w") as f:
            f.write("weight")
        with open("model.json", "w") as f:
            f.write("model")
        res = api.push("test/test", ["weights.h5", "model.json"])
    assert res[0].status_code == 200

def test_push_no_project(request_mocker, upload_url, query_project):
    query_project(request_mocker)
    upload_url(request_mocker)
    with pytest.raises(wandb.Error):
        res = api.push("test", "weights.json")

def test_upload_success(request_mocker, upload_url):
    upload_url(request_mocker)
    res = api.upload_file("https://weights.url", open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))
    assert res.status_code == 200

def test_upload_failure(request_mocker, upload_url):
    upload_url(request_mocker, status_code=500)
    with pytest.raises(wandb.Error):
        api.upload_file("https://weights.url", open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))

def test_upload_failure_resumable(request_mocker, upload_url):
    upload_url(request_mocker, status_code=500)
    request_mocker.register_uri('PUT', "https://weights.url", request_headers={'Content-Length': '0'}, headers={'Range': "0-10"}, status_code=308)
    request_mocker.register_uri('PUT', "https://weights.url", request_headers={'Content-Range': 'bytes 10-51373/51373'})
    res = api.upload_file("https://weights.url", open(os.path.join(os.path.dirname(__file__), "fixtures/test.h5")))
    assert res.status_code == 200

def test_config(mocker):
    parser = mocker.patch.object(api, "config_parser")
    parser.sections.return_value = ["default"]
    parser.options.return_value = ["project", "entity"]
    parser.get.side_effect = ["test_model", "test_entity"]
    assert api.config() == {
        'base_url': 'https://api.wandb.ai',
        'entity': 'test_entity',
        'project': 'test_model',
        'section': 'default',
        'bucket': 'default'
    }

def test_default_config():
    assert wandb.Api({'base_url': 'http://localhost'}, load_config=False).config() == {
        'base_url': 'http://localhost', 
        'entity': 'models', 
        'section': 'default',
        'bucket': 'default'
    }
