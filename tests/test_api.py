#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_wandb
----------------------------------

Tests for the `wandb.Api` module.
"""
import pytest, gql, os, requests
from .api_mocks import *

from contextlib import contextmanager

import wandb
api = wandb.Api(load_config=False)

def test_models_success(request_mocker, query_models):
    query_models(request_mocker)
    res = api.list_models()
    assert len(res) == 3

def test_models_failure(request_mocker, query_models):
    query_models(request_mocker, status_code=400, error="Bummer")
    with pytest.raises(wandb.Error):
        api.list_models()

def test_model_download_urls(request_mocker, query_model):
    query_model(request_mocker)
    res = api.download_urls("test")
    assert res == {'weights': 'https://weights.url', 'model': 'https://model.url'}

def test_model_upload_urls(request_mocker, query_model):
    query_model(request_mocker)
    res = api.upload_urls("test")
    assert res == {'h5': ['weights', 'https://weights.url'], 'json': ['model', 'https://model.url']}

def test_download_success(request_mocker, download_url):
    download_url(request_mocker)
    res = api.download_file("https://weights.url")
    assert res[1].status_code == 200

def test_download_failure(request_mocker, download_url):
    download_url(request_mocker, status_code=500)
    with pytest.raises(wandb.Error):
        api.download_file("https://weights.url")

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

def test_create_revision(request_mocker, mutate_revision):
    mutate_revision(request_mocker)
    rev = api.create_revision("test", description="My new revision")
    assert rev["version"] == "0.0.1"

def test_create_revision_no_description(request_mocker, mutate_revision):
    mutate_revision(request_mocker)
    rev = api.create_revision("test")
    assert rev["version"] == "0.0.1"

def test_config(mocker):
    parser = mocker.patch.object(api, "config_parser")
    parser.sections.return_value = ["default"]
    parser.options.return_value = ["model", "entity"]
    parser.get.side_effect = ["test_model", "test_entity"]
    assert api.config() == {
        'base_url': 'https://api.wandb.ai',
        'entity': 'test_entity',
        'model': 'test_model',
        'section': 'default',
        'tag': 'default'
    }

def test_default_config():
    assert wandb.Api({'base_url': 'http://localhost'}, load_config=False).config() == {
        'base_url': 'http://localhost', 
        'entity': 'models', 
        'section': 'default',
        'tag': 'default'
    }
