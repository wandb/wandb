import os
import tempfile

import pytest
import wandb


def test_no_root_dir_access__uses_temp_dir(tmp_path, monkeypatch):
    temp_dir = tempfile.gettempdir()
    root_dir = tmp_path / "create_dir_test"
    os.makedirs(root_dir, exist_ok=True)

    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: not (
            mode == (os.R_OK | os.W_OK) and str(path) == str(root_dir)
        ),
    )

    with wandb.init(dir=root_dir, mode="offline") as run:
        run.log({"test": 1})

    assert run.settings.root_dir == temp_dir


def test_no_temp_dir_access__throws_error(monkeypatch):
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    temp_dir = tempfile.gettempdir()
    monkeypatch.setattr(
        os,
        "access",
        lambda path, mode: not (
            mode == (os.R_OK | os.W_OK) and str(path) == str(temp_dir)
        ),
    )

    with pytest.raises(ValueError):
        with wandb.init(dir=temp_dir, mode="offline") as run:
            run.log({"test": 1})


def test_makedirs_raises_oserror__uses_temp_dir(tmp_path, monkeypatch):
    tmp_file = tmp_path / "test.txt"
    tmp_file.touch()

    with wandb.init(dir=str(tmp_file / "dir2"), mode="offline") as run:
        run.log({"test": 1})

    assert run.settings.root_dir == tempfile.gettempdir()


def test_avoids_sync_dir_conflict(mocker):
    # Make the run start time the same for all runs.
    mocker.patch("time.time", return_value=123)

    with wandb.init(mode="offline", id="sync-dir-test") as run1:
        pass
    with wandb.init(mode="offline", id="sync-dir-test") as run2:
        pass
    with wandb.init(mode="offline", id="sync-dir-test") as run3:
        pass

    assert run2.settings.sync_dir == run1.settings.sync_dir + "-1"
    assert run3.settings.sync_dir == run1.settings.sync_dir + "-2"
