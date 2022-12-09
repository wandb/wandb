"""
file upload tests.
"""

import os
from unittest import mock

import pytest
from wandb.sdk.internal.internal_api import Api as InternalApi


@pytest.fixture
def mock_upload_file_retry():
    with mock.patch.object(InternalApi, "upload_file_retry") as upload_file_retry:
        yield upload_file_retry


def test_file_upload_good(mock_run, publish_util, relay_server, user):
    run = mock_run(use_magic_mock=True)

    def begin_fn(interface):
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    with relay_server() as relay:
        publish_util(run, begin_cb=begin_fn, files=files)

    assert "test.txt" in relay.context.get_run_uploaded_files(run.id)


def test_calls_upload_file_retry(
    mock_run, publish_util, relay_server, user, mock_upload_file_retry: mock.Mock
):
    run = mock_run(use_magic_mock=True)

    def begin_fn(interface):
        with open(os.path.join(run.dir, "test.txt"), "w") as f:
            f.write("TEST TEST")

    files = [dict(files_dict=dict(files=[("test.txt", "now")]))]
    with relay_server():
        publish_util(run, begin_cb=begin_fn, files=files)

    target_uploads = [
        c[0][0] for c in mock_upload_file_retry.call_args_list if "/test.txt" in c[0][0]
    ]
    assert len(target_uploads) == 1
