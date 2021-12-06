import multiprocessing
import os
import pytest
import platform
import sys
import subprocess
import threading
import time
import wandb

from six.moves import queue

from wandb.sdk.internal.meta import Meta
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.interface.interface_queue import InterfaceQueue


@pytest.fixture()
def record_q():
    return multiprocessing.Queue()


@pytest.fixture()
def result_q():
    return multiprocessing.Queue()


@pytest.fixture()
def interface(record_q):
    return InterfaceQueue(record_q=record_q)


@pytest.fixture()
def meta(test_settings, interface):
    return Meta(settings=test_settings, interface=interface)


@pytest.fixture()
def sm(
    runner,
    git_repo,
    record_q,
    result_q,
    test_settings,
    meta,
    mock_server,
    mocked_run,
    interface,
):
    test_settings.save_code = True
    sm = SendManager(
        settings=test_settings,
        record_q=record_q,
        result_q=result_q,
        interface=interface,
    )
    meta._interface.publish_run(mocked_run)
    sm.send(record_q.get())
    yield sm


def test_meta_probe(mock_server, meta, sm, record_q, log_debug, monkeypatch):
    orig_exists = os.path.exists
    orig_call = subprocess.call
    monkeypatch.setattr(
        os.path,
        "exists",
        lambda path: True if "conda-meta" in path else orig_exists(path),
    )
    monkeypatch.setattr(
        subprocess,
        "call",
        lambda cmd, **kwargs: kwargs["stdout"].write("CONDA YAML")
        if "conda" in cmd
        else orig_call(cmd, **kwargs),
    )
    with open("README", "w") as f:
        f.write("Testing")
    meta.probe()
    meta.write()
    sm.send(record_q.get())
    sm.finish()
    print(mock_server.ctx)
    assert len(mock_server.ctx["storage?file=wandb-metadata.json"]) == 1
    assert len(mock_server.ctx["storage?file=requirements.txt"]) == 1
    # py27 doesn't like my patching for conda-environment, just skipping
    if sys.version_info > (3, 0):
        assert len(mock_server.ctx["storage?file=conda-environment.yaml"]) == 1
    assert len(mock_server.ctx["storage?file=diff.patch"]) == 1


def test_executable_outside_cwd(mock_server, meta):
    meta._settings.update(program="asdf.py")
    meta.probe()
    assert meta.data.get("codePath") is None
    assert meta.data["program"] == "asdf.py"


def test_jupyter_name(meta, mocked_ipython):
    meta._settings.update(notebook_name="test_nb")
    meta.probe()
    assert meta.data["program"] == "test_nb"


def test_jupyter_path(meta, mocked_ipython):
    # not actually how jupyter setup works but just to test the meta paths
    meta._settings.update(_jupyter_path="dummy/path")
    meta.probe()
    assert meta.data["program"] == "dummy/path"
    assert meta.data.get("root") is not None


# TODO: test actual code saving
def test_commmit_hash_sent_correctly(test_settings, git_repo):
    # disable_git is False is by default
    # so run object should have git info
    run = wandb.init(settings=test_settings)
    assert run._last_commit is not None
    assert run._last_commit == git_repo.last_commit
    assert run._remote_url is None
    run.finish()


def test_commit_hash_not_sent_when_disable(test_settings, git_repo, disable_git_save):
    run = wandb.init(settings=test_settings)
    assert git_repo.last_commit
    assert run._last_commit is None
    run.finish()


@pytest.fixture
def poll_meta_done():
    def _poll_meta_done(interface, timeout):
        start = time.time()
        done = False
        delay = 0.1

        while not done and time.time() - start < timeout:
            response = interface.communicate_meta_poll()
            print(response)
            if response is not None and response.completed:
                done = True
            time.sleep(delay)
            delay = min(delay * 2, 2)

        print("poll", interface.record_q)
        if response is None:
            return None, None
        return response.completed, response.timed_out

    return _poll_meta_done


def test_meta_probe_long_timeout(
    backend_interface, monkeypatch, git_repo, poll_meta_done
):
    timeout = 20
    with backend_interface() as interface:
        monkeypatch.setattr(
            wandb.sdk.internal.meta.Meta, "get_timeout", lambda x: timeout
        )
        interface.communicate_meta_start()
        completed, timed_out = poll_meta_done(interface, timeout)
        assert completed is True
        assert timed_out is False


def test_meta_probe_short_timeout(
    backend_interface, monkeypatch, git_repo, poll_meta_done
):
    timeout = 0.01
    with backend_interface() as interface:
        monkeypatch.setattr(
            wandb.sdk.internal.meta.Meta, "get_timeout", lambda x: timeout
        )
        interface.communicate_meta_start()
        completed, timed_out = poll_meta_done(interface, 20)
        assert completed is True
        assert timed_out is True
