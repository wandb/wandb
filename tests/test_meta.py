import pytest
import os
from six.moves import queue

from wandb.internal.meta import Meta
from wandb.internal.sender import SendManager


@pytest.fixture()
def resp_q():
    return queue.Queue()


@pytest.fixture()
def req_q():
    return queue.Queue()


@pytest.fixture()
def meta(test_settings, req_q):
    return Meta(test_settings, req_q, queue.Queue())


@pytest.fixture()
def sm(runner, git_repo, resp_q, test_settings, meta, mock_server, mocked_run, req_q):
    test_settings.root_dir = os.getcwd()
    sm = SendManager(test_settings, resp_q)
    meta._interface.send_run(mocked_run)
    sm.send(req_q.get())
    yield sm


def test_meta_probe(mock_server, meta, sm, req_q):
    with open("README", "w") as f:
        f.write("Testing")
    meta.probe()
    meta.write()
    sm.send(req_q.get())
    sm.finish()
    print(mock_server.ctx)
    assert len(mock_server.ctx["storage?file=wandb-metadata.json"]) == 1
    assert len(mock_server.ctx["storage?file=requirements.txt"]) == 1
    assert len(mock_server.ctx["storage?file=diff.patch"]) == 1

# TODO: test actual code saving