"""These test the full stack by launching a real backend server.  You won't get
credit for coverage of the backend logic in these tests.  See test_sender.py for testing
specific backend logic, or wandb_test.py for testing frontend logic.

Be sure to use `test_settings` or an isolated directory
"""
import importlib
import os
import shutil
import time
from unittest import mock

import pytest
import wandb
import wandb.env as env

reload_fn = importlib.reload

# TODO: better debugging, if the backend process fails to start we currently
#  don't get any debug information even in the internal logs.  For now I'm writing
#  logs from all tests that use test_settings to tests/logs/TEST_NAME.  If you're
#  having tests just hang forever, I suggest running test/test_sender to see backend
#  errors until we ensure we propagate the errors up.


def test_resume_auto_success(wandb_init):
    run = wandb_init(reinit=True, resume=True)
    run.finish()
    assert not os.path.exists(run.settings.resume_fname)


def test_include_exclude_config_keys(wandb_init):
    config = {
        "foo": 1,
        "bar": 2,
        "baz": 3,
    }
    run = wandb_init(
        reinit=True, resume=True, config=config, config_exclude_keys=("bar",)
    )

    assert run.config["foo"] == 1
    assert run.config["baz"] == 3
    assert "bar" not in run.config
    run.finish()

    run = wandb_init(
        reinit=True, resume=True, config=config, config_include_keys=("bar",)
    )

    assert run.config["bar"] == 2
    assert "foo" not in run.config
    assert "baz" not in run.config
    run.finish()

    with pytest.raises(
        wandb.errors.UsageError,
        match="Expected at most only one of exclude or include",
    ):
        wandb_init(
            reinit=True,
            resume=True,
            config=config,
            config_include_keys=("bar",),
            config_exclude_keys=("bar",),
        )


def test_ignore_globs_wandb_files(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(settings=dict(ignore_globs=["requirements.txt"]))
        run.finish()
    assert sorted(relay.context.get_run_uploaded_files(run.id)) == sorted(
        ["wandb-metadata.json", "config.yaml", "wandb-summary.json"]
    )


def _remove_dir_if_exists(path):
    """Recursively removes directory. Be careful"""
    if os.path.isdir(path):
        shutil.rmtree(path)


def test_dir_on_import():
    """Ensures that `import wandb` does not create a local storage directory"""
    default_path = os.path.join(os.getcwd(), "wandb")
    custom_env_path = os.path.join(os.getcwd(), "env_custom")

    # Test for the base case
    _remove_dir_if_exists(default_path)
    reload_fn(wandb)
    assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
        default_path
    )

    # test for the case that the env variable is set
    with mock.patch.dict(os.environ, {"WANDB_DIR": custom_env_path}):
        _remove_dir_if_exists(default_path)
        reload_fn(wandb)
        assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
            default_path
        )
        assert not os.path.isdir(
            custom_env_path
        ), f"Unexpected directory at {custom_env_path}"


def test_dir_on_init(wandb_init):
    """Ensures that `wandb.init()` creates the proper directory and nothing else"""
    default_path = os.path.join(os.getcwd(), "wandb")

    # Clear env if set
    names_to_remove = {env.DIR}
    modified_environ = {k: v for k, v in os.environ.items() if k not in names_to_remove}
    with mock.patch.dict("os.environ", modified_environ, clear=True):
        # Test for the base case
        reload_fn(wandb)
        _remove_dir_if_exists(default_path)
        run = wandb_init()
        run.finish()
        assert os.path.isdir(default_path), "Expected directory at {}".format(
            default_path
        )


def test_dir_on_init_env(wandb_init):
    """Ensures that `wandb.init()` w/ env variable set creates the proper directory and nothing else"""
    default_path = os.path.join(os.getcwd(), "wandb")
    custom_env_path = os.path.join(os.getcwd(), "env_custom")

    # test for the case that the env variable is set
    with mock.patch.dict(os.environ, {env.DIR: custom_env_path}):
        if not os.path.isdir(custom_env_path):
            os.makedirs(custom_env_path)
        reload_fn(wandb)
        _remove_dir_if_exists(default_path)
        run = wandb_init()
        run.finish()
        assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
            default_path
        )
        assert os.path.isdir(custom_env_path), "Expected directory at {}".format(
            custom_env_path
        )
        # And for the duplicate-run case
        _remove_dir_if_exists(default_path)
        run = wandb_init()
        run.finish()
        assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
            default_path
        )
        assert os.path.isdir(custom_env_path), "Expected directory at {}".format(
            custom_env_path
        )


def test_dir_on_init_dir(wandb_init):
    """Ensures that `wandb.init(dir=DIR)` creates the proper directory and nothing else"""
    default_path = os.path.join(os.getcwd(), "wandb")
    dir_name = "dir_custom"
    custom_dir_path = os.path.join(os.getcwd(), dir_name)

    # test for the case that the dir is set
    reload_fn(wandb)
    _remove_dir_if_exists(default_path)
    if not os.path.isdir(custom_dir_path):
        os.makedirs(custom_dir_path)
    run = wandb_init(dir="./" + dir_name)
    run.finish()
    assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
        default_path
    )
    assert os.path.isdir(custom_dir_path), "Expected directory at {}".format(
        custom_dir_path
    )
    # And for the duplicate-run case
    _remove_dir_if_exists(default_path)
    run = wandb_init(dir="./" + dir_name)
    run.finish()
    assert not os.path.isdir(default_path), "Unexpected directory at {}".format(
        default_path
    )
    assert os.path.isdir(custom_dir_path), "Expected directory at {}".format(
        custom_dir_path
    )


@pytest.mark.parametrize(
    "version, message",
    [
        ("0.10.2", "is available!  To upgrade, please run:"),
        ("0.10.0", "WARNING wandb version 0.10.0 has been recalled"),
        ("0.9.0", "ERROR wandb version 0.9.0 has been retired"),
    ],
)  # TODO should we mock pypi?
def test_versions_messages(wandb_init, capsys, version, message):
    with mock.patch("wandb.__version__", version):
        run = wandb_init(settings=dict(console="off"))
        assert message in capsys.readouterr().err
        run.finish()


def test_end_to_end_preempting(relay_server, wandb_init):

    with relay_server() as relay:
        run = wandb_init(settings=dict(console="off"))
        run.mark_preempting()

        # poll for message arrival
        for _ in range(3):
            preempting = relay.context.entries[run.id].get("preempting")
            if preempting:
                break
            time.sleep(1)
        assert any(preempting)
        run.finish()


def test_end_to_end_preempting_via_module_func(relay_server, wandb_init):
    with relay_server() as relay:
        run = wandb_init(settings=dict(console="off"))
        run.log({"a": 1})
        run.mark_preempting()

        # poll for message arrival
        for _ in range(3):
            preempting = relay.context.entries[run.id].get("preempting")
            if preempting:
                break
            time.sleep(1)
        assert any(preempting)
        run.finish()
