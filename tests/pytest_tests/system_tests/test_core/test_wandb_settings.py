"""settings test."""

import datetime
import os
import platform

import pytest  # type: ignore
from wandb.sdk import wandb_settings

Source = wandb_settings.Source

# TODO: replace wandb_init with mock_run or move tests to integration tests

# ------------------------------------
# test Settings class
# ------------------------------------


# note: patching os.environ because other tests may have created env variables
# that are not in the default environment, which would cause these test to fail.
# setting {"USERNAME": "test"} because on Windows getpass.getuser() would otherwise fail.
@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_sync_dir(wandb_init):
    run = wandb_init(settings={"mode": "offline"})
    print(run._settings.sync_dir)
    assert run._settings.sync_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_sync_file(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings.sync_file == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", f"run-{run.id}.wandb")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_files_dir(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings.files_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", "files")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_tmp_dir(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings.tmp_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", "tmp")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_tmp_code_dir(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings._tmp_code_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", "tmp", "code")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_log_symlink_user(wandb_init):
    run = wandb_init(settings=dict(mode="offline"))
    assert os.path.realpath(run._settings.log_symlink_user) == os.path.abspath(
        run._settings.log_user
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_log_symlink_internal(wandb_init):
    run = wandb_init(mode="offline")
    assert os.path.realpath(run._settings.log_symlink_internal) == os.path.abspath(
        run._settings.log_internal
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
def test_sync_symlink_latest(wandb_init):
    run = wandb_init(mode="offline")
    time_tag = datetime.datetime.strftime(
        run._settings._start_datetime, "%Y%m%d_%H%M%S"
    )
    assert os.path.realpath(run._settings.sync_symlink_latest) == os.path.abspath(
        os.path.join(".", "wandb", f"offline-run-{time_tag}-{run.id}")
    )
    run.finish()
