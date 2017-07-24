import pytest, os
from click.testing import CliRunner
from threading import Thread

import wandb, time

def test_watches_for_all_changes(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test")
        t = Thread(target=sync.watch)
        t.start()
        with open("some_file.h5", "w") as f:
            f.write("My great changes")
        t.join()
        time.sleep(.2)
        assert api.push.called

def test_watches_for_specific_change(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test")
        t = Thread(target=sync.watch, args=(["rad.txt"],))
        t.start()
        with open("rad.txt", "a") as f:
            f.write("something great")
        t.join()
        time.sleep(.2)
        assert api.push.called

def test_watches_for_glob_change(mocker):
    with CliRunner().isolated_filesystem():
        api = mocker.MagicMock()
        sync = wandb.Sync(api, "test")
        t = Thread(target=sync.watch, args=(["*.txt"],))
        t.start()
        time.sleep(.2)
        with open("file.txt", "a") as f:
            f.write("great")
        t.join()
        time.sleep(.2)
        assert api.push.called
