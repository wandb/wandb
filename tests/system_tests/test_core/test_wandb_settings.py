"""settings test."""

import os
import platform
from unittest import mock

import git
import pytest
import wandb
from wandb import env


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


def test_manual_git_run_metadata_from_settings(wandb_backend_spy):
    remote_url = "git@github.com:me/my-repo.git"
    commit = "29c15e893e36efad84001f4484b4813fbacd55a0"

    with wandb.init(
        settings={
            "git_remote_url": remote_url,
            "git_commit": commit,
        },
    ) as run:
        pass

    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.remote(run_id=run.id) == remote_url
        assert snapshot.commit(run_id=run.id) == commit


def test_manual_git_run_metadata_from_environ(wandb_backend_spy):
    remote_url = "git@github.com:me/my-repo.git"
    commit = "29c15e893e36efad84001f4484b4813fbacd55a0"
    with mock.patch.dict(
        os.environ,
        {
            env.GIT_REMOTE_URL: remote_url,
            env.GIT_COMMIT: commit,
        },
    ):
        with wandb.init() as run:
            pass

    with wandb_backend_spy.freeze() as snapshot:
        assert snapshot.remote(run_id=run.id) == remote_url
        assert snapshot.commit(run_id=run.id) == commit


def test_git_root(runner, wandb_backend_spy):
    path = "./foo"
    remote_url = "https://foo:@github.com/FooTest/Foo.git"
    with runner.isolated_filesystem():
        with git.Repo.init(path) as repo:
            repo.create_remote("origin", remote_url)
            repo.index.commit("initial commit")
        with mock.patch.dict(os.environ, {env.GIT_ROOT: path}):
            with wandb.init() as run:
                pass

        with wandb_backend_spy.freeze() as snapshot:
            assert snapshot.remote(run_id=run.id) == repo.remote().url
            assert snapshot.commit(run_id=run.id) == repo.head.commit.hexsha
