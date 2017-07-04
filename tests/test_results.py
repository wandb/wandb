#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_results
----------------------------------

Tests for the `wandb.Results` module.
"""
import pytest
from wandb import Results
from .api_mocks import *
from click.testing import CliRunner

def test_push_success(request_mocker, upload_url, query_project):
    #mock = query_project(request_mocker)
    payload = project("test", files={
        'edges': [
            {'node': {
                'name': 'results.csv',
                'url': 'https://results.csv',
                'md5': 'fakemd5'
            }}]})
    success_or_failure({'model': payload})(request_mocker)
    #upload_url(request_mocker)
    mock = request_mocker.register_uri('PUT', 'https://results.csv', status_code=200)
    with CliRunner().isolated_filesystem():
        with Results("test/test") as res:
            res.write(input="Test", output=False, truth=True, loss=0.89)
    assert mock.called