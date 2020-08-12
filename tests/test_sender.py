import os
import pytest
from six.moves import queue
import threading
import time
import shutil

from wandb.util import mkdir_exists_ok
from wandb.internal.sender import SendManager
from wandb.interface import constants
from wandb.interface.interface import BackendSender


@pytest.fixture()
def process_q():
    return queue.Queue()


@pytest.fixture()
def notify_q():
    return queue.Queue()


@pytest.fixture()
def resp_q():
    return queue.Queue()


@pytest.fixture()
def req_q():
    return queue.Queue()


@pytest.fixture()
def sender(process_q, req_q, resp_q, notify_q):
    return BackendSender(
        process_queue=process_q,
        request_queue=req_q,
        notify_queue=notify_q,
        response_queue=resp_q,
    )


@pytest.fixture()
def sm(
    runner, process_q, notify_q, resp_q, test_settings, sender, mock_server, mocked_run,
):
    with runner.isolated_filesystem():
        test_settings.root_dir = os.getcwd()
        sm = SendManager(test_settings, process_q, notify_q, resp_q)
        sender.send_run(mocked_run)
        notify_q.get()
        sm.send(process_q.get())
        yield sm


@pytest.fixture()
def get_message(notify_q, process_q, req_q):
    def _get_message(timeout=None):
        try:
            i = notify_q.get(timeout=timeout)
        except queue.Empty:
            return None
        if i == constants.NOTIFY_PROCESS:
            return process_q.get()
        elif i == constants.NOTIFY_REQUEST:
            return req_q.get()

    return _get_message


@pytest.fixture()
def start_rcv_thread(get_message):
    stop_event = threading.Event()

    def start_rcv(send_manager):
        def rcv():
            while not stop_event.is_set():
                payload = get_message(timeout=0.1)
                if payload:
                    send_manager.send(payload)

        t = threading.Thread(target=rcv)
        t.daemon = True
        t.start()

    yield start_rcv
    stop_event.set()


def test_send_status_request(mock_server, sm, sender, start_rcv_thread):
    mock_server.ctx["stopped"] = True
    start_rcv_thread(sm)

    status_resp = sender.send_status_request(check_stop_req=True)
    assert status_resp is not None
    assert status_resp.run_should_stop


def test_parallel_requests(mock_server, sm, sender, start_rcv_thread):
    mock_server.ctx["stopped"] = True
    work_queue = queue.Queue()
    start_rcv_thread(sm)

    def send_sync_request(i):
        work_queue.get()
        if i % 3 == 0:
            status_resp = sender.send_status_request(check_stop_req=True)
            assert status_resp is not None
            assert status_resp.run_should_stop
        elif i % 3 == 1:
            status_resp = sender.send_status_request(check_stop_req=False)
            assert status_resp is not None
            assert not status_resp.run_should_stop
        elif i % 3 == 2:
            summary_resp = sender.send_get_summary_sync()
            assert summary_resp is not None
            assert hasattr(summary_resp, "item")
        work_queue.task_done()

    for i in range(10):
        work_queue.put(None)
        t = threading.Thread(target=send_sync_request, args=(i,))
        t.daemon = True
        t.start()

    work_queue.join()


def test_resume_success(
    mocked_run,
    test_settings,
    mock_server,
    sender,
    process_q,
    notify_q,
    resp_q,
    start_rcv_thread,
):
    test_settings.resume = "allow"
    mock_server.ctx["resume"] = True
    sm = SendManager(test_settings, process_q, notify_q, resp_q)
    start_rcv_thread(sm)

    run_result = sender.send_run_sync(mocked_run)
    assert run_result.HasField("error") is False
    assert run_result.run.starting_step == 16


def test_resume_error_never(
    mocked_run,
    test_settings,
    mock_server,
    sender,
    process_q,
    notify_q,
    resp_q,
    start_rcv_thread,
):
    test_settings.resume = "never"
    mock_server.ctx["resume"] = True
    sm = SendManager(test_settings, process_q, notify_q, resp_q)
    start_rcv_thread(sm)

    run_result = sender.send_run_sync(mocked_run)
    assert run_result.HasField("error")
    assert (
        run_result.error.message == "resume='never' but run (%s) exists" % mocked_run.id
    )


def test_resume_error_must(
    mocked_run,
    test_settings,
    mock_server,
    sender,
    process_q,
    notify_q,
    resp_q,
    start_rcv_thread,
):
    test_settings.resume = "must"
    mock_server.ctx["resume"] = False
    sm = SendManager(test_settings, process_q, notify_q, resp_q)
    start_rcv_thread(sm)

    run_result = sender.send_run_sync(mocked_run)
    assert run_result.HasField("error")
    assert (
        run_result.error.message
        == "resume='must' but run (%s) doesn't exist" % mocked_run.id
    )


def test_save_live_existing_file(mocked_run, mock_server, sender, sm, process_q):
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(process_q.get())
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_live_write_after_policy(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(process_q.get())
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_live_multi_write(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(process_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 2


def test_save_live_glob_multi_write(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("checkpoints/*", "live")]})
    sm.send(process_q.get())
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


def test_save_rename_file(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("test.txt", "live")]})
    sm.send(process_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    shutil.copy(test_file, test_file.replace("test.txt", "test-copy.txt"))
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1
    assert len(mock_server.ctx["storage?file=test-copy.txt"]) == 1


def test_save_end_write_after_policy(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("test.txt", "end")]})
    sm.send(process_q.get())
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_existing_file(mocked_run, mock_server, sender, sm, process_q):
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.send_files({"files": [("test.txt", "end")]})
    sm.send(process_q.get())
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_multi_write(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("test.txt", "end")]})
    sm.send(process_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_write_after_policy(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("test.txt", "now")]})
    sm.send(process_q.get())
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_existing_file(mocked_run, mock_server, sender, sm, process_q):
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.send_files({"files": [("test.txt", "now")]})
    sm.send(process_q.get())
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_multi_write(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("test.txt", "now")]})
    sm.send(process_q.get())
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sm.finish()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_glob_multi_write(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("checkpoints/*", "now")]})
    sm.send(process_q.get())
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


def test_save_now_relative_path(mocked_run, mock_server, sender, sm, process_q):
    sender.send_files({"files": [("foo/test.txt", "now")]})
    sm.send(process_q.get())
    test_file = os.path.join(mocked_run.dir, "foo", "test.txt")
    mkdir_exists_ok(os.path.dirname(test_file))
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    sm.finish()
    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 1


def test_save_now_twice(mocked_run, mock_server, sender, sm, process_q):
    file_path = os.path.join("foo", "test.txt")
    sender.send_files({"files": [(file_path, "now")]})
    sm.send(process_q.get())
    test_file = os.path.join(mocked_run.dir, file_path)
    mkdir_exists_ok(os.path.dirname(test_file))
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sender.send_files({"files": [(file_path, "now")]})
    sm.send(process_q.get())
    sm.finish()
    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 2


# TODO: test other sender methods
