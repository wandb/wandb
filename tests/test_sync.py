import pytest
import os
from click.testing import CliRunner
from threading import Thread
from .api_mocks import upload_logs, upsert_run
from freezegun import freeze_time

import wandb
import time


def mock_stop(*args):
    pass


def test_watches_for_all_changes(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test", dir='.')
        sync.stop = mock_stop
        sync.watch(['*'])
        with open("some_file.h5", "w") as f:
            f.write("My great changes")
        # Fuck if I know why this makes shit work...
        time.sleep(1)
        assert api.upsert_run.called
        assert api.push.called


def test_watches_for_specific_change(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test", dir='.')
        sync.stop = mock_stop
        sync.watch(["rad.txt"])
        with open("rad.txt", "a") as f:
            f.write("something great")
        time.sleep(1)
        assert api.push.called


def test_watches_for_subdir_change(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test", dir='.')
        sync.stop = mock_stop
        sync.watch(["./subdir/*.txt"])
        os.mkdir('subdir')
        with open("subdir/rad.txt", "a") as f:
            f.write("something great")
        time.sleep(1)
        assert api.push.called


def test_ignores_hidden_folders(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test", dir='.')
        sync.stop = mock_stop
        sync.watch(["*"])
        os.mkdir('.subdir')
        with open(".subdir/rad.txt", "a") as f:
            f.write("something great")
        time.sleep(1)
        assert not api.push.called


def test_watches_for_glob_change(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test", dir='.')
        sync.stop = mock_stop
        sync.watch(["*.txt"])
        with open("file.txt", "a") as f:
            f.write("great")
        time.sleep(1)
        assert api.push.called

# def test_syncs_log(mocker, upload_logs, upsert_run, request_mocker):
#    with CliRunner().isolated_filesystem():
#        api = wandb.Api()
#        run_mock = upsert_run(request_mocker)
#        with freeze_time("1981-12-09 12:00:01"):
#            sync = wandb.Sync(api, dir='.')
#        log_mock = upload_logs(request_mocker, sync.run_id)
#        sync.stop = mock_stop
#        sync.watch('*')
#        assert run_mock.called
#        print("My logger")
#        print("1")
#        print("2")
#        print("3")
#        print("4th and final")
#        time.sleep(1)
#        assert log_mock.called
