import os
import pytest
import platform
import sys
import subprocess
import threading

from six.moves import queue

# TODO: consolidate dynamic imports
PY3 = sys.version_info.major == 3 and sys.version_info.minor >= 6
if PY3:
    from wandb.sdk.internal.meta import Meta
    from wandb.sdk.internal.sender import SendManager
    from wandb.sdk.interface.interface import BackendSender
else:
    from wandb.sdk_py27.internal.meta import Meta
    from wandb.sdk_py27.internal.sender import SendManager
    from wandb.sdk_py27.interface.interface import BackendSender


@pytest.fixture()
def record_q():
    return queue.Queue()


@pytest.fixture()
def result_q():
    return queue.Queue()


@pytest.fixture()
def interface(record_q):
    return BackendSender(record_q=record_q)


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


# TODO: test actual code saving
