"""
test_wandb
----------------------------------

Tests for the `wandb.apis.PublicApi` module.
"""

import os

import requests
import wandb
from wandb.sdk.lib import filesystem


def test_run_files(runner, mock_server, api):
    with runner.isolated_filesystem():
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


def test_run_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        file = run.file("weights.h5")
        assert not os.path.exists("weights.h5")
        file.download()
        assert os.path.exists("weights.h5")


def test_run_upload_file(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_run_upload_file_relative(runner, mock_server, api):
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        filesystem.mkdir_exists_ok("foo")
        os.chdir("foo")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb", "../")
        assert file.url == "https://api.wandb.ai/storage?file=foo/new_file.pb"


def test_upload_file_retry(runner, mock_server, api):
    mock_server.set_context("fail_storage_count", 4)
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_upload_file_inject_retry(runner, mock_server, api, inject_requests):
    match = inject_requests.Match(path_suffix="/storage", count=2)
    inject_requests.add(
        match=match, requests_error=requests.exceptions.ConnectionError()
    )
    with runner.isolated_filesystem():
        run = api.run("test/test/test")
        with open("new_file.pb", "w") as f:
            f.write("TEST")
        file = run.upload_file("new_file.pb")
        assert file.url == "https://api.wandb.ai/storage?file=new_file.pb"


def test_reports(mock_server, api):
    path = "test-entity/test-project"
    reports = api.reports(path)
    # calling __len__, __getitem__, or __next__ on a Reports object
    # triggers the actual API call to fetch data w/ pagination.
    length = len(reports)
    assert length == 1
    assert reports[0].description == "test-description"
    assert reports[0].pageCount == 0
    assert reports[1].pageCount == 1


def test_run_wait_until_finished(runner, mock_server, api, capsys):
    run = api.run("test/test/test")
    run.wait_until_finished()
    out, _ = capsys.readouterr()
    status = mock_server.ctx["run_state"]
    assert f"Run finished with status: {status}" in out


def test_invite_user(mock_server, api):
    t = api.team("test")
    assert t.invite("test@test.com")
    assert t.invite("test")
    mock_server.set_context("graphql_conflict", True)
    assert t.invite("conflict") is False


def test_delete_member(mock_server, api):
    t = api.team("test")
    assert t.members[0].delete()
    mock_server.set_context("graphql_conflict", True)
    assert t.invite("conflict") is False
