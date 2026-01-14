"""Test the full stack by launching a real backend server.

You won't get credit for coverage of the backend logic in these tests.  See
test_sender.py for testing specific backend logic, or wandb_test.py for testing frontend
logic.

Be sure to use `test_settings` or an isolated directory
"""

import importlib
import os
import shutil
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


def test_resume_auto_success(user):
    run = wandb.init(resume=True)
    run.finish()
    assert not os.path.exists(run.settings.resume_fname)


def test_include_exclude_config_keys(user):
    config = {
        "foo": 1,
        "bar": 2,
        "baz": 3,
    }

    with wandb.init(
        resume=True,
        config=config,
        config_exclude_keys=("bar",),
    ) as run:
        assert run.config["foo"] == 1
        assert run.config["baz"] == 3
        assert "bar" not in run.config

    with wandb.init(
        resume=True,
        config=config,
        config_include_keys=("bar",),
    ) as run:
        assert run.config["bar"] == 2
        assert "foo" not in run.config
        assert "baz" not in run.config

    with pytest.raises(
        wandb.errors.UsageError,
        match="Expected at most only one of exclude or include",
    ):
        wandb.init(
            resume=True,
            config=config,
            config_include_keys=("bar",),
            config_exclude_keys=("bar",),
        )


def _remove_dir_if_exists(path):
    """Recursively removes directory. Be careful."""
    if os.path.isdir(path):
        shutil.rmtree(path)


def test_dir_on_import():
    """Ensure that `import wandb` does not create a local storage directory."""
    default_path = os.path.join(os.getcwd(), "wandb")
    custom_env_path = os.path.join(os.getcwd(), "env_custom")

    # Test for the base case
    _remove_dir_if_exists(default_path)
    reload_fn(wandb)
    assert not os.path.isdir(default_path), f"Unexpected directory at {default_path}"

    # test for the case that the env variable is set
    with mock.patch.dict(os.environ, {"WANDB_DIR": custom_env_path}):
        _remove_dir_if_exists(default_path)
        reload_fn(wandb)
        assert not os.path.isdir(default_path), (
            f"Unexpected directory at {default_path}"
        )
        assert not os.path.isdir(custom_env_path), (
            f"Unexpected directory at {custom_env_path}"
        )


def test_dir_on_init(user):
    """Ensure that `wandb.init()` creates the proper directory and nothing else."""
    default_path = os.path.join(os.getcwd(), "wandb")

    # Clear env if set
    names_to_remove = {env.DIR}
    modified_environ = {k: v for k, v in os.environ.items() if k not in names_to_remove}
    with mock.patch.dict("os.environ", modified_environ, clear=True):
        # Test for the base case
        reload_fn(wandb)
        _remove_dir_if_exists(default_path)
        run = wandb.init()
        run.finish()
        assert os.path.isdir(default_path), f"Expected directory at {default_path}"


def test_dir_on_init_env(user):
    """Ensure that `wandb.init()` w/ env variable set creates the proper directory and nothing else."""
    default_path = os.path.join(os.getcwd(), "wandb")
    custom_env_path = os.path.join(os.getcwd(), "env_custom")

    # test for the case that the env variable is set
    with mock.patch.dict(os.environ, {env.DIR: custom_env_path}):
        if not os.path.isdir(custom_env_path):
            os.makedirs(custom_env_path)
        reload_fn(wandb)
        _remove_dir_if_exists(default_path)
        run = wandb.init()
        run.finish()
        assert not os.path.isdir(default_path), (
            f"Unexpected directory at {default_path}"
        )
        assert os.path.isdir(custom_env_path), (
            f"Expected directory at {custom_env_path}"
        )
        # And for the duplicate-run case
        _remove_dir_if_exists(default_path)
        run = wandb.init()
        run.finish()
        assert not os.path.isdir(default_path), (
            f"Unexpected directory at {default_path}"
        )
        assert os.path.isdir(custom_env_path), (
            f"Expected directory at {custom_env_path}"
        )


def test_dir_on_init_dir(user):
    """Ensure that `wandb.init(dir=DIR)` creates the proper directory and nothing else."""
    default_path = os.path.join(os.getcwd(), "wandb")
    dir_name = "dir_custom"
    custom_dir_path = os.path.join(os.getcwd(), dir_name)

    # test for the case that the dir is set
    reload_fn(wandb)
    _remove_dir_if_exists(default_path)
    if not os.path.isdir(custom_dir_path):
        os.makedirs(custom_dir_path)
    run = wandb.init(dir="./" + dir_name)
    run.finish()
    assert not os.path.isdir(default_path), f"Unexpected directory at {default_path}"
    assert os.path.isdir(custom_dir_path), f"Expected directory at {custom_dir_path}"
    # And for the duplicate-run case
    _remove_dir_if_exists(default_path)
    run = wandb.init(dir="./" + dir_name)
    run.finish()
    assert not os.path.isdir(default_path), f"Unexpected directory at {default_path}"
    assert os.path.isdir(custom_dir_path), f"Expected directory at {custom_dir_path}"


def test_mark_preempting(wandb_backend_spy):
    with wandb.init() as run:
        run.mark_preempting()

    # `mark_preempting` is expected to update the run ASAP, but to avoid
    # sleeping in the test, we just check whether the message was ever sent
    # after waiting for the run to flush.
    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.was_ever_preempting(run_id=run.id)
