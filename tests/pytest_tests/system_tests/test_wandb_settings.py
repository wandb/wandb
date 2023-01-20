"""
settings test.
"""

import datetime
import os
import platform
from unittest import mock

import pytest  # type: ignore
import wandb
from wandb.sdk import wandb_login, wandb_settings

Source = wandb_settings.Source

# TODO: replace wandb_init with mock_run or move tests to integration tests

# ------------------------------------
# test Settings class
# ------------------------------------


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend crashes on Windows in CI",
)
@mock.patch.dict(
    os.environ, {"WANDB_START_METHOD": "thread", "USERNAME": "test"}, clear=True
)
def test_console_run(wandb_init):
    run = wandb_init(mode="offline", settings={"console": "auto"})
    assert run._settings.console == "auto"
    assert run._settings._console == wandb_settings.SettingsConsole.WRAP
    run.finish()


# note: patching os.environ because other tests may have created env variables
# that are not in the default environment, which would cause these test to fail.
# setting {"USERNAME": "test"} because on Windows getpass.getuser() would otherwise fail.
@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_sync_dir(wandb_init):
    run = wandb_init(mode="offline")
    print(run._settings.sync_dir)
    assert run._settings.sync_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_sync_file(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings.sync_file == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", f"run-{run.id}.wandb")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_files_dir(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings.files_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", "files")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_tmp_dir(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings.tmp_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", "tmp")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_tmp_code_dir(wandb_init):
    run = wandb_init(mode="offline")
    assert run._settings._tmp_code_dir == os.path.realpath(
        os.path.join(".", "wandb", "latest-run", "tmp", "code")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_log_symlink_user(wandb_init):
    run = wandb_init(mode="offline")
    assert os.path.realpath(run._settings.log_symlink_user) == os.path.abspath(
        run._settings.log_user
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_log_symlink_internal(wandb_init):
    run = wandb_init(mode="offline")
    assert os.path.realpath(run._settings.log_symlink_internal) == os.path.abspath(
        run._settings.log_internal
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows", reason="backend crashes on Windows in CI"
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_sync_symlink_latest(wandb_init):
    run = wandb_init(mode="offline")
    time_tag = datetime.datetime.strftime(
        run._settings._start_datetime, "%Y%m%d_%H%M%S"
    )
    assert os.path.realpath(run._settings.sync_symlink_latest) == os.path.abspath(
        os.path.join(".", "wandb", f"offline-run-{time_tag}-{run.id}")
    )
    run.finish()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend crashes on Windows in CI, likely bc of the overloaded env",
)
@mock.patch.dict(os.environ, {"USERNAME": "test"}, clear=True)
def test_console(runner, test_settings):
    with runner.isolated_filesystem():
        test_settings = test_settings()
        run = wandb.init(mode="offline")
        assert run._settings.console == "auto"
        assert run._settings._console == wandb_settings.SettingsConsole.REDIRECT
        test_settings.update({"console": "off"}, source=Source.BASE)
        assert test_settings._console == wandb_settings.SettingsConsole.OFF
        test_settings.update({"console": "wrap"}, source=Source.BASE)
        assert test_settings._console == wandb_settings.SettingsConsole.WRAP
        run.finish()


def test_code_saving_save_code_env_false(wandb_init, test_settings):
    settings = test_settings()
    settings.update({"save_code": None}, source=Source.BASE)
    with mock.patch.dict("os.environ", WANDB_SAVE_CODE="false"):
        run = wandb_init(settings=settings)
        assert run.settings.save_code is False
        run.finish()


def test_code_saving_disable_code(wandb_init, test_settings):
    settings = test_settings()
    settings.update({"save_code": None}, source=Source.BASE)
    with mock.patch.dict("os.environ", WANDB_DISABLE_CODE="true"):
        run = wandb_init(settings=settings)
        assert run.settings.save_code is False
        run.finish()


def test_silent_run(wandb_init, test_settings):
    test_settings = test_settings()
    test_settings.update({"silent": "true"}, source=Source.SETTINGS)
    assert test_settings.silent is True
    run = wandb_init(settings=test_settings)
    assert run._settings.silent is True
    run.finish()


@pytest.mark.skip(reason="causes other tests that depend on capsys to fail")
def test_silent_env_run(wandb_init):
    with mock.patch.dict("os.environ", WANDB_SILENT="true"):
        run = wandb_init()
        assert run._settings.silent is True
        run.finish()


def test_strict_run(wandb_init, test_settings):
    test_settings = test_settings()
    test_settings.update({"strict": "true"}, source=Source.SETTINGS)
    assert test_settings.strict is True
    run = wandb_init(settings=test_settings)
    assert run._settings.strict is True
    run.finish()


def test_show_info_run(wandb_init):
    run = wandb_init()
    assert run._settings.show_info is True
    run.finish()


def test_show_info_false_run(wandb_init, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_info": "false"}, source=Source.SETTINGS)
    run = wandb_init(settings=test_settings)
    assert run._settings.show_info is False
    run.finish()


def test_show_warnings_run(wandb_init, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_warnings": "true"}, source=Source.SETTINGS)
    run = wandb_init(settings=test_settings)
    assert run._settings.show_warnings is True
    run.finish()


def test_show_warnings_false_run(wandb_init, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_warnings": "false"}, source=Source.SETTINGS)
    run = wandb_init(settings=test_settings)
    assert run._settings.show_warnings is False
    run.finish()


def test_show_errors_run(wandb_init, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_errors": True}, source=Source.SETTINGS)
    run = wandb_init(settings=test_settings)
    assert run._settings.show_errors is True
    run.finish()


def test_show_errors_false_run(wandb_init, test_settings):
    test_settings = test_settings()
    test_settings.update({"show_errors": False}, source=Source.SETTINGS)
    run = wandb_init(settings=test_settings)
    assert run._settings.show_errors is False
    run.finish()


def test_not_jupyter(wandb_init):
    run = wandb_init()
    assert run._settings._jupyter is False
    run.finish()


def test_resume_fname_run(wandb_init):
    run = wandb_init()
    assert run._settings.resume_fname == os.path.join(
        run._settings.root_dir, "wandb", "wandb-resume.json"
    )
    run.finish()


def test_wandb_dir_run(wandb_init):
    run = wandb_init()
    assert os.path.abspath(run._settings.wandb_dir) == os.path.abspath(
        os.path.join(run._settings.root_dir, "wandb")
    )
    run.finish()


def test_override_login_settings(user, test_settings):
    wlogin = wandb_login._WandbLogin()
    login_settings = test_settings().copy()
    login_settings.update(show_emoji=True)
    wlogin.setup({"_settings": login_settings})
    assert wlogin._settings.show_emoji is True


def test_override_login_settings_with_dict(user):
    wlogin = wandb_login._WandbLogin()
    login_settings = dict(show_emoji=True)
    wlogin.setup({"_settings": login_settings})
    assert wlogin._settings.show_emoji is True


def test_setup_offline(user, test_settings):
    # this is to increase coverage
    login_settings = test_settings().copy()
    login_settings.update(mode="offline")
    assert wandb.setup(settings=login_settings)._instance._get_entity() is None
    assert wandb.setup(settings=login_settings)._instance._load_viewer() is None
