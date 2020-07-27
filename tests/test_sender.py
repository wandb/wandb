import os
import pytest
from six.moves import queue
import time
import shutil

from wandb.util import mkdir_exists_ok
from wandb.internal.sender import SendManager
from wandb.interface.interface import BackendSender


@pytest.fixture()
def resp_q():
    return queue.Queue()


@pytest.fixture()
def req_q():
    return queue.Queue()


@pytest.fixture()
def sender(req_q):
    return BackendSender(process_queue=req_q, notify_queue=queue.Queue())


@pytest.fixture()
def sm(runner, resp_q, test_settings, sender, mock_server, mocked_run, req_q):
    with runner.isolated_filesystem():
        test_settings.root_dir = os.getcwd()
        sm = SendManager(test_settings, resp_q)
        sender.send_run(mocked_run)
        sm.send(req_q.get())
        yield sm


def test_save_live_existing_file(mocked_run, mock_server, sender, sm, req_q):
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(req_q.get())
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_live_write_after_policy(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(req_q.get())
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_live_multi_write(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(req_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 2


def test_save_live_glob_multi_write(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("checkpoints/*", "live")]})
    sm.send(req_q.get())
    mkdir_exists_ok(os.path.join(mocked_run.dir, "checkpoints"))
    test_file_1 = os.path.join(mocked_run.dir, "checkpoints", "test_1.txt")
    test_file_2 = os.path.join(mocked_run.dir, "checkpoints", "test_2.txt")
    with open(test_file_1, "w") as f:
        f.write("TEST TEST")
    time.sleep(0.5)
    with open(test_file_1, "w") as f:
        f.write("TEST TEST TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file_2, "w") as f:
        f.write("TEST TEST TEST TEST")
    with open(test_file_1, "w") as f:
        f.write("TEST TEST TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=checkpoints/test_1.txt"]) == 2
    assert len(mock_server.ctx["storage?file=checkpoints/test_2.txt"]) == 1


def test_save_rename_file(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(req_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    shutil.copy(test_file, test_file.replace("test.txt", "test-copy.txt"))
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1
    assert len(mock_server.ctx["storage?file=test-copy.txt"]) == 1


def test_save_end_write_after_policy(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("test.txt", "end")]})
    sm.send(req_q.get())
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_existing_file(mocked_run, mock_server, sender, sm, req_q):
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.send_files({"files": [("test.txt", "end")]})
    sm.send(req_q.get())
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_multi_write(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("test.txt", "end")]})
    sm.send(req_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_write_after_policy(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("test.txt", "now")]})
    sm.send(req_q.get())
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_existing_file(mocked_run, mock_server, sender, sm, req_q):
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.send_files({"files": [("test.txt", "now")]})
    sm.send(req_q.get())
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_multi_write(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("test.txt", "now")]})
    sm.send(req_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_glob_multi_write(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("checkpoints/*", "now")]})
    sm.send(req_q.get())
    mkdir_exists_ok(os.path.join(mocked_run.dir, "checkpoints"))
    test_file_1 = os.path.join(mocked_run.dir, "checkpoints", "test_1.txt")
    test_file_2 = os.path.join(mocked_run.dir, "checkpoints", "test_2.txt")
    with open(test_file_1, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file_2, "w") as f:
        f.write("TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=checkpoints/test_1.txt"]) == 1
    assert len(mock_server.ctx["storage?file=checkpoints/test_2.txt"]) == 1


def test_save_now_relative_path(mocked_run, mock_server, sender, sm, req_q):
    sender.send_files({"files": [("foo/test.txt", "now")]})
    sm.send(req_q.get())
    test_file = os.path.join(mocked_run.dir, "foo", "test.txt")
    mkdir_exists_ok(os.path.dirname(test_file))
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    sm.finish()
    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 1


def test_save_now_twice(mocked_run, mock_server, sender, sm, req_q):
    file_path = os.path.join("foo", "test.txt")
    sender.send_files({"files": [(file_path, "now")]})
    sm.send(req_q.get())
    test_file = os.path.join(mocked_run.dir, file_path)
    mkdir_exists_ok(os.path.dirname(test_file))
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sender.send_files({"files": [(file_path, "now")]})
    sm.send(req_q.get())
    sm.finish()
    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 2
# TODO: test other sender methods
