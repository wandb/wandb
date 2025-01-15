from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Iterator

import pytest

from .wandb_backend_spy import WandbBackendProxy, WandbBackendSpy, spy_proxy

#: See https://docs.pytest.org/en/stable/how-to/plugins.html#requiring-loading-plugins-in-a-test-module-or-conftest-file
pytest_plugins = ("tests.system_tests.backend_fixtures",)


class ConsoleFormatter:
    BOLD = "\033[1m"
    CODE = "\033[2m"
    MAGENTA = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"


# TODO: remove this and port the relevant tests to Go
# --------------------------------
# Fixtures for internal test point
# --------------------------------
import threading  # noqa: E402
from queue import Empty, Queue  # noqa: E402

from wandb.sdk.interface.interface_queue import InterfaceQueue  # noqa: E402
from wandb.sdk.internal import context  # noqa: E402
from wandb.sdk.internal.handler import HandleManager  # noqa: E402
from wandb.sdk.internal.sender import SendManager  # noqa: E402
from wandb.sdk.internal.settings_static import SettingsStatic  # noqa: E402
from wandb.sdk.internal.writer import WriteManager  # noqa: E402
from wandb.sdk.lib.mailbox import Mailbox  # noqa: E402


@pytest.fixture
def internal_result_q():
    return Queue()


@pytest.fixture
def internal_sender_q():
    return Queue()


@pytest.fixture
def internal_writer_q() -> Queue:
    return Queue()


@pytest.fixture
def internal_record_q() -> Queue:
    return Queue()


@pytest.fixture
def internal_process() -> MockProcess:
    return MockProcess()


class MockProcess:
    def __init__(self) -> None:
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive


@pytest.fixture
def _internal_mailbox() -> Mailbox:
    return Mailbox()


@pytest.fixture
def _internal_sender(
    internal_record_q, internal_result_q, internal_process, _internal_mailbox
):
    return InterfaceQueue(
        record_q=internal_record_q,
        result_q=internal_result_q,
        process=internal_process,
        mailbox=_internal_mailbox,
    )


@pytest.fixture
def _internal_context_keeper():
    context_keeper = context.ContextKeeper()
    yield context_keeper


@pytest.fixture
def internal_sm(
    runner,
    internal_sender_q,
    internal_result_q,
    _internal_sender,
    _internal_context_keeper,
):
    def helper(settings):
        with runner.isolated_filesystem():
            sm = SendManager(
                settings=SettingsStatic(settings.to_proto()),
                record_q=internal_sender_q,
                result_q=internal_result_q,
                interface=_internal_sender,
                context_keeper=_internal_context_keeper,
            )
            return sm

    yield helper


@pytest.fixture
def stopped_event():
    stopped = threading.Event()
    yield stopped


@pytest.fixture
def internal_hm(
    runner,
    internal_record_q,
    internal_result_q,
    internal_writer_q,
    _internal_sender,
    stopped_event,
    _internal_context_keeper,
):
    def helper(settings):
        with runner.isolated_filesystem():
            hm = HandleManager(
                settings=SettingsStatic(settings.to_proto()),
                record_q=internal_record_q,
                result_q=internal_result_q,
                stopped=stopped_event,
                writer_q=internal_writer_q,
                interface=_internal_sender,
                context_keeper=_internal_context_keeper,
            )
            return hm

    yield helper


@pytest.fixture
def internal_wm(
    runner,
    internal_writer_q,
    internal_result_q,
    internal_sender_q,
    _internal_sender,
    stopped_event,
    _internal_context_keeper,
):
    def helper(settings):
        with runner.isolated_filesystem():
            wandb_file = settings.sync_file

            # this is hacky, but we don't have a clean rundir always
            # so lets at least make sure we can write to this dir
            run_dir = Path(wandb_file).parent
            os.makedirs(run_dir)

            wm = WriteManager(
                settings=SettingsStatic(settings.to_proto()),
                record_q=internal_writer_q,
                result_q=internal_result_q,
                sender_q=internal_sender_q,
                interface=_internal_sender,
                context_keeper=_internal_context_keeper,
            )
            return wm

    yield helper


@pytest.fixture
def internal_get_record():
    def _get_record(input_q, timeout=None):
        try:
            i = input_q.get(timeout=timeout)
        except Empty:
            return None
        return i

    return _get_record


@pytest.fixture
def start_send_thread(
    internal_sender_q, internal_get_record, stopped_event, internal_process
):
    def start_send(send_manager):
        def target():
            try:
                while True:
                    payload = internal_get_record(
                        input_q=internal_sender_q, timeout=0.1
                    )
                    if payload:
                        send_manager.send(payload)
                    elif stopped_event.is_set():
                        break
            except Exception:
                stopped_event.set()
                internal_process._alive = False

        t = threading.Thread(target=target)
        t.name = "testing-sender"
        t.daemon = True
        t.start()
        return t

    yield start_send
    stopped_event.set()


@pytest.fixture
def start_write_thread(
    internal_writer_q, internal_get_record, stopped_event, internal_process
):
    def start_write(write_manager):
        def target():
            try:
                while True:
                    payload = internal_get_record(
                        input_q=internal_writer_q, timeout=0.1
                    )
                    if payload:
                        write_manager.write(payload)
                    elif stopped_event.is_set():
                        break
            except Exception:
                stopped_event.set()
                internal_process._alive = False

        t = threading.Thread(target=target)
        t.name = "testing-writer"
        t.daemon = True
        t.start()
        return t

    yield start_write
    stopped_event.set()


@pytest.fixture
def start_handle_thread(internal_record_q, internal_get_record, stopped_event):
    def start_handle(handle_manager):
        def target():
            while True:
                payload = internal_get_record(input_q=internal_record_q, timeout=0.1)
                if payload:
                    handle_manager.handle(payload)
                elif stopped_event.is_set():
                    break

        t = threading.Thread(target=target)
        t.name = "testing-handler"
        t.daemon = True
        t.start()
        return t

    yield start_handle
    stopped_event.set()


@pytest.fixture
def _start_backend(
    internal_hm,
    internal_sm,
    internal_wm,
    _internal_sender,
    start_handle_thread,
    start_write_thread,
    start_send_thread,
):
    def start_backend_func(run=None, initial_run=True, initial_start=True):
        ihm = internal_hm(run.settings)
        iwm = internal_wm(run.settings)
        ism = internal_sm(run.settings)
        ht = start_handle_thread(ihm)
        wt = start_write_thread(iwm)
        st = start_send_thread(ism)
        if initial_run:
            handle = _internal_sender.deliver_run(run)
            result = handle.wait(timeout=60)
            run_result = result.run_result
            if initial_start:
                handle = _internal_sender.deliver_run_start(run_result.run)
                handle.wait(timeout=60)
        return ht, wt, st

    yield start_backend_func


@pytest.fixture
def _stop_backend(
    _internal_sender,
    # collect_responses,
):
    def stop_backend_func(threads=None):
        threads = threads or ()
        handle = _internal_sender.deliver_exit(0)
        record = handle.wait(timeout=60)
        assert record

        _internal_sender.join()
        for t in threads:
            t.join()

    yield stop_backend_func


@pytest.fixture
def backend_interface(_start_backend, _stop_backend, _internal_sender):
    @contextmanager
    def backend_context(run, initial_run=True, initial_start=True):
        threads = _start_backend(
            run=run,
            initial_run=initial_run,
            initial_start=initial_start,
        )
        try:
            yield _internal_sender
        finally:
            _stop_backend(threads=threads)

    return backend_context


@pytest.fixture
def publish_util(backend_interface):
    def publish_util_helper(
        run,
        metrics=None,
        history=None,
        artifacts=None,
        files=None,
        begin_cb=None,
        end_cb=None,
        initial_start=False,
    ):
        metrics = metrics or []
        history = history or []
        artifacts = artifacts or []
        files = files or []

        with backend_interface(run=run, initial_start=initial_start) as interface:
            if begin_cb:
                begin_cb(interface)
            for m in metrics:
                interface._publish_metric(m)
            for h in history:
                if "run" not in h:
                    h["run"] = run
                interface.publish_history(**h)
            for a in artifacts:
                interface.publish_artifact(**a)
            for f in files:
                interface.publish_files(**f)
            if end_cb:
                end_cb(interface)

    yield publish_util_helper


# --------------------------------
# Fixtures for full test point
# --------------------------------


def pytest_addoption(parser: pytest.Parser):
    # note: we default to "function" scope to ensure the environment is
    # set up properly when running the tests in parallel with pytest-xdist.
    parser.addoption(
        "--user-scope",
        default="function",  # or "function" or "session" or "module"
        help='cli to set scope of fixture "user-scope"',
    )

    parser.addoption(
        "--wandb-verbose",
        action="store_true",
        default=False,
        help="Run tests in verbose mode",
    )


def determine_scope(fixture_name, config):
    return config.getoption("--user-scope")


@pytest.fixture(scope="session")
def wandb_verbose(request):
    return request.config.getoption("--wandb-verbose", default=False)


@pytest.fixture(scope=determine_scope)
def user(mocker, backend_fixture_factory) -> Iterator[str]:
    username = backend_fixture_factory.make_user()
    envvars = {
        "WANDB_API_KEY": username,
        "WANDB_ENTITY": username,
        "WANDB_USERNAME": username,
    }
    mocker.patch.dict(os.environ, envvars)
    yield username


@pytest.fixture(scope="session")
def wandb_backend_proxy_server(
    local_wandb_backend,
) -> Generator[WandbBackendProxy, None, None]:
    """Session fixture that starts up a proxy server for the W&B backend."""
    with spy_proxy(
        target_host=local_wandb_backend.host,
        target_port=local_wandb_backend.base_port,
    ) as proxy:
        yield proxy


@pytest.fixture(scope="function")
def wandb_backend_spy(
    user,
    wandb_backend_proxy_server: WandbBackendProxy,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[WandbBackendSpy, None, None]:
    """Fixture that allows spying on requests to the W&B backend.

    This patches WANDB_BASE_URL and creates a fake user for the test
    setting auth-related environment variables.

    Usage:

        def test_something(wandb_backend_spy):
            with wandb.init() as run:
                run.log({"x": 1})

            with wandb_backend_spy.freeze() as snapshot:
                history = snapshot.history(run_id=run.id)
                assert history[0]["x"] == 1
    """

    # Use a fake API key for the test.
    _ = user

    # Connect to the proxy to spy on requests:
    monkeypatch.setenv(
        "WANDB_BASE_URL",
        f"http://127.0.0.1:{wandb_backend_proxy_server.port}",
    )

    with wandb_backend_proxy_server.spy() as spy:
        yield spy
