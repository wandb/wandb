import os
import pytest
import platform
import threading

from six.moves import queue
from wandb.internal.meta import Meta
from wandb.internal.sender import SendManager
from wandb.interface.interface import BackendSender


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
def sm(runner, git_repo, record_q, result_q, test_settings, meta, mock_server, mocked_run, interface):
    sm = SendManager(settings=test_settings, record_q=record_q, result_q=result_q, interface=interface)
    meta._interface.publish_run(mocked_run)
    sm.send(record_q.get())
    yield sm


@pytest.mark.skipif(platform.system() == "Windows", reason="git stopped working")
def test_meta_probe(mock_server, meta, sm, record_q):
    with open("README", "w") as f:
        f.write("Testing")
    meta.probe()
    meta.write()
    sm.send(record_q.get())
    sm.finish()
    print(mock_server.ctx)
    assert len(mock_server.ctx["storage?file=wandb-metadata.json"]) == 1
    assert len(mock_server.ctx["storage?file=requirements.txt"]) == 1
    assert len(mock_server.ctx["storage?file=diff.patch"]) == 1


# TODO: test actual code saving
