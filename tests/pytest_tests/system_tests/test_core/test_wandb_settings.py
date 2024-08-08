"""settings test."""

import os
import platform
from unittest import mock

import git
import pytest  # type: ignore
from wandb import env
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
    time_tag = run._settings._start_datetime
    assert os.path.realpath(run._settings.sync_symlink_latest) == os.path.abspath(
        os.path.join(".", "wandb", f"offline-run-{time_tag}-{run.id}")
    )
    run.finish()


def test_manual_git_run_metadata_from_settings(
    relay_server,
    wandb_init,
):
    remote_url = "git@github.com:me/my-repo.git"
    commit = "29c15e893e36efad84001f4484b4813fbacd55a0"
    with relay_server() as relay:
        run = wandb_init(
            settings={
                "git_remote_url": remote_url,
                "git_commit": commit,
            },
        )
        run.finish()

        run_attrs = relay.context.get_run_attrs(run.id)
        assert run_attrs.remote == remote_url
        assert run_attrs.commit == commit


def test_manual_git_run_metadata_from_environ(relay_server, wandb_init):
    remote_url = "git@github.com:me/my-repo.git"
    commit = "29c15e893e36efad84001f4484b4813fbacd55a0"
    with relay_server() as relay:
        with mock.patch.dict(
            os.environ,
            {
                env.GIT_REMOTE_URL: remote_url,
                env.GIT_COMMIT: commit,
            },
        ):
            run = wandb_init()
            run.finish()

        run_attrs = relay.context.get_run_attrs(run.id)
        assert run_attrs.remote == remote_url
        assert run_attrs.commit == commit


def test_git_root(runner, relay_server, wandb_init):
    path = "./foo"
    remote_url = "https://foo:@github.com/FooTest/Foo.git"
    with runner.isolated_filesystem():
        with git.Repo.init(path) as repo:
            repo.create_remote("origin", remote_url)
            repo.index.commit("initial commit")
        with relay_server() as relay:
            with mock.patch.dict(os.environ, {env.GIT_ROOT: path}):
                run = wandb_init()
                run.finish()
            run_attrs = relay.context.get_run_attrs(run.id)
            assert run_attrs.remote == repo.remote().url
            assert run_attrs.commit == repo.head.commit.hexsha
