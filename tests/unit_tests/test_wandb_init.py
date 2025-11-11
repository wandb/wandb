import os
import tempfile

import pytest
import wandb
from wandb.sdk.lib import telemetry
from wandb.sdk.wandb_init import _WandbInit
from wandb.sdk.wandb_setup import singleton


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


def test_api_key_passed_to_login(mocker):
    mock_login = mocker.patch("wandb.sdk.wandb_login._login")
    test_api_key = "test_api_key_12345"

    wandb_setup = singleton()
    init_settings = wandb.Settings(api_key=test_api_key)

    wandb_init = _WandbInit(wandb_setup, telemetry.TelemetryRecord())
    wandb_init.maybe_login(init_settings)

    mock_login.assert_called_once()
    call_kwargs = mock_login.call_args.kwargs
    assert call_kwargs["key"] == test_api_key
