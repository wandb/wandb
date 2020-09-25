import os
import pytest
from six.moves import queue
import threading
import time
import shutil

from wandb.util import mkdir_exists_ok
from wandb.internal.handler import HandleManager
from wandb.internal.sender import SendManager
from wandb.interface import constants
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
def sender_q():
    return queue.Queue()


@pytest.fixture()
def writer_q():
    return queue.Queue()


@pytest.fixture()
def process():
    # FIXME: return mocked process (needs is_alive())
    return MockProcess()


class MockProcess():
    def __init__(self):
        pass

    def is_alive(self):
        return True


@pytest.fixture()
def sender(record_q, result_q, process):
    return BackendSender(
        record_q=record_q,
        result_q=result_q,
        process=process,
    )


@pytest.fixture()
def sm(
    runner, sender_q, result_q, test_settings, mock_server, interface,
):
    with runner.isolated_filesystem():
        test_settings.root_dir = os.getcwd()
        sm = SendManager(settings=test_settings, record_q=sender_q, result_q=result_q, interface=interface,)
        yield sm


@pytest.fixture()
def hm(
    runner, record_q, result_q, test_settings, mock_server, sender_q, writer_q, interface,
):
    with runner.isolated_filesystem():
        test_settings.root_dir = os.getcwd()
        stopped = threading.Event()
        hm = HandleManager(settings=test_settings, record_q=record_q, result_q=result_q, stopped=stopped,
                sender_q=sender_q, writer_q=writer_q, interface=interface,)
        yield hm


@pytest.fixture()
def get_record():
    def _get_record(input_q, timeout=None):
        try:
            i = input_q.get(timeout=timeout)
        except queue.Empty:
            return None
        return i

    return _get_record


@pytest.fixture()
def start_send_thread(sender_q, get_record):
    stop_event = threading.Event()

    def start_send(send_manager):
        def target():
            while not stop_event.is_set():
                payload = get_record(input_q=sender_q, timeout=0.1)
                if payload:
                    send_manager.send(payload)

        t = threading.Thread(target=target)
        t.daemon = True
        t.start()

    yield start_send
    stop_event.set()


@pytest.fixture()
def start_handle_thread(record_q, get_record):
    stop_event = threading.Event()

    def start_handle(handle_manager):
        def target():
            while not stop_event.is_set():
                payload = get_record(input_q=record_q, timeout=0.1)
                if payload:
                    handle_manager.handle(payload)

        t = threading.Thread(target=target)
        t.daemon = True
        t.start()

    yield start_handle
    stop_event.set()


@pytest.fixture()
def start_backend(mocked_run, hm, sm, sender, start_handle_thread, start_send_thread,):
    def start_backend_func(initial_run=True):
        start_handle_thread(hm)
        start_send_thread(sm)
        if initial_run:
            _ = sender.communicate_run(mocked_run)

    yield start_backend_func


@pytest.fixture()
def stop_backend(mocked_run, hm, sm, sender, start_handle_thread, start_send_thread,):
    def stop_backend_func():
        _ = sender.communicate_exit(0)

    yield stop_backend_func


def test_send_status_request(mock_server, sender, start_backend,):
    mock_server.ctx["stopped"] = True
    start_backend()

    status_resp = sender.communicate_status(check_stop_req=True)
    assert status_resp is not None
    assert status_resp.run_should_stop


def test_parallel_requests(mock_server, sender, start_backend,):
    mock_server.ctx["stopped"] = True
    work_queue = queue.Queue()
    start_backend()

    def send_sync_request(i):
        work_queue.get()
        if i % 3 == 0:
            status_resp = sender.communicate_status(check_stop_req=True)
            assert status_resp is not None
            assert status_resp.run_should_stop
        elif i % 3 == 1:
            status_resp = sender.communicate_status(check_stop_req=False)
            assert status_resp is not None
            assert not status_resp.run_should_stop
        elif i % 3 == 2:
            summary_resp = sender.communicate_summary()
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
    start_backend,
):
    test_settings.resume = "allow"
    mock_server.ctx["resume"] = True
    start_backend(initial_run=False)

    run_result = sender.communicate_run(mocked_run)
    assert run_result.HasField("error") is False
    assert run_result.run.starting_step == 16


def test_resume_error_never(
    mocked_run,
    test_settings,
    mock_server,
    sender,
    start_backend,
):
    test_settings.resume = "never"
    mock_server.ctx["resume"] = True
    start_backend(initial_run=False)

    run_result = sender.communicate_run(mocked_run)
    assert run_result.HasField("error")
    assert (
        run_result.error.message == "resume='never' but run (%s) exists" % mocked_run.id
    )


def test_resume_error_must(
    mocked_run,
    test_settings,
    mock_server,
    sender,
    start_backend,
):
    test_settings.resume = "must"
    mock_server.ctx["resume"] = False
    start_backend(initial_run=False)

    run_result = sender.communicate_run(mocked_run)
    assert run_result.HasField("error")
    assert (
        run_result.error.message
        == "resume='must' but run (%s) doesn't exist" % mocked_run.id
    )


def test_save_live_existing_file(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.publish_files({"files": [("test.txt", "live")]})
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_live_write_after_policy(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("test.txt", "live")]})
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_live_multi_write(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("test.txt", "live")]})
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 2


def test_save_live_glob_multi_write(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("checkpoints/*", "live")]})
    mkdir_exists_ok(os.path.join(mocked_run.dir, "checkpoints"))
    test_file_1 = os.path.join(mocked_run.dir, "checkpoints", "test_1.txt")
    test_file_2 = os.path.join(mocked_run.dir, "checkpoints", "test_2.txt")
    with open(test_file_1, "w") as f:
        f.write("TEST TEST")
    time.sleep(1.5)
    with open(test_file_1, "w") as f:
        f.write("TEST TEST TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file_2, "w") as f:
        f.write("TEST TEST TEST TEST")
    with open(test_file_1, "w") as f:
        f.write("TEST TEST TEST TEST TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=checkpoints/test_1.txt"]) == 3
    assert len(mock_server.ctx["storage?file=checkpoints/test_2.txt"]) == 1


def test_save_rename_file(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("test.txt", "live")]})
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    shutil.copy(test_file, test_file.replace("test.txt", "test-copy.txt"))
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1
    assert len(mock_server.ctx["storage?file=test-copy.txt"]) == 1


def test_save_end_write_after_policy(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("test.txt", "end")]})
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_existing_file(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.publish_files({"files": [("test.txt", "end")]})
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_end_multi_write(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("test.txt", "end")]})
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_write_after_policy(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("test.txt", "now")]})
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_existing_file(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    with open(os.path.join(mocked_run.dir, "test.txt"), "w") as f:
        f.write("TEST TEST")
    sender.publish_files({"files": [("test.txt", "now")]})
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_now_multi_write(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("test.txt", "now")]})
    test_file = os.path.join(mocked_run.dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=test.txt"]) == 1


def test_save_glob_multi_write(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("checkpoints/*", "now")]})
    mkdir_exists_ok(os.path.join(mocked_run.dir, "checkpoints"))
    test_file_1 = os.path.join(mocked_run.dir, "checkpoints", "test_1.txt")
    test_file_2 = os.path.join(mocked_run.dir, "checkpoints", "test_2.txt")
    with open(test_file_1, "w") as f:
        f.write("TEST TEST")
    # File system polling happens every second
    time.sleep(1.5)
    with open(test_file_2, "w") as f:
        f.write("TEST TEST TEST TEST")
    stop_backend()
    assert len(mock_server.ctx["storage?file=checkpoints/test_1.txt"]) == 1
    assert len(mock_server.ctx["storage?file=checkpoints/test_2.txt"]) == 1


def test_save_now_relative_path(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    sender.publish_files({"files": [("foo/test.txt", "now")]})
    test_file = os.path.join(mocked_run.dir, "foo", "test.txt")
    mkdir_exists_ok(os.path.dirname(test_file))
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    stop_backend()
    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 1


def test_save_now_twice(mocked_run, mock_server, sender, start_backend, stop_backend,):
    start_backend()
    file_path = os.path.join("foo", "test.txt")
    sender.publish_files({"files": [(file_path, "now")]})
    test_file = os.path.join(mocked_run.dir, file_path)
    mkdir_exists_ok(os.path.dirname(test_file))
    with open(test_file, "w") as f:
        f.write("TEST TEST")
    time.sleep(1.5)
    with open(test_file, "w") as f:
        f.write("TEST TEST TEST TEST")
    sender.publish_files({"files": [(file_path, "now")]})
    stop_backend()
    print("DAMN DUDE", mock_server.ctx)
    assert len(mock_server.ctx["storage?file=foo/test.txt"]) == 2


# TODO: test other sender methods
