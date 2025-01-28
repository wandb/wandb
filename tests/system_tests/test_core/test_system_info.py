import platform
import queue
import unittest.mock

import pytest
import wandb
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.system.system_info import SystemInfo
from wandb.sdk.lib import ipython


@pytest.fixture()
def record_q():
    return queue.Queue()


@pytest.fixture()
def result_q():
    return queue.Queue()


@pytest.fixture()
def interface(record_q):
    return InterfaceQueue(record_q=record_q)


@pytest.fixture()
def meta(interface):
    def meta_helper(settings):
        return SystemInfo(settings=settings, interface=interface)

    yield meta_helper


def test_executable_outside_cwd(meta, test_settings):
    meta = meta(test_settings(dict(program="asdf.py")))
    data = meta.probe()
    assert data.get("codePath") is None
    assert data["program"] == "asdf.py"


def test_jupyter_name(meta, test_settings, monkeypatch):
    monkeypatch.setattr(ipython, "in_jupyter", lambda: True)
    meta = meta(test_settings(dict(notebook_name="test_nb")))
    data = meta.probe()
    assert data["program"] == "test_nb"


def test_jupyter_path(meta, test_settings, monkeypatch, git_repo):
    monkeypatch.setattr(ipython, "in_jupyter", lambda: True)
    # not actually how jupyter setup works but just to test the meta paths
    meta = meta(test_settings(dict(x_jupyter_path="dummy/path")))
    data = meta.probe()
    assert data["program"] == "dummy/path"
    assert data.get("root") is not None


# TODO: test actual code saving
# fixme:
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend sometimes crashes on Windows in CI",
)
def test_commit_hash_sent_correctly(user, git_repo):
    # disable_git is False is by default
    # so run object should have git info
    run = wandb.init()
    assert run._settings.git_commit is not None
    assert run._settings.git_commit == git_repo.last_commit
    assert run._settings.git_remote_url is None
    run.finish()


# fixme:
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend sometimes crashes on Windows in CI",
)
def test_commit_hash_not_sent_when_disable(user, git_repo):
    with unittest.mock.patch.dict("os.environ", WANDB_DISABLE_GIT="true"):
        run = wandb.init()
        assert git_repo.last_commit
        assert run._settings.git_commit is None
        run.finish()
