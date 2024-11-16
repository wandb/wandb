import dataclasses
import json
import os
import pathlib
import platform
import secrets
import string
import subprocess
import sys
import unittest.mock
import urllib.parse
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any, Dict, Generator, Iterator, List, Optional, Union

import pytest
import requests
import wandb
import wandb.old.settings
import wandb.util

from .relay import (
    DeliberateHTTPError,
    InjectedResponse,
    RelayServer,
    TokenizedCircularPattern,
)
from .wandb_backend_spy import WandbBackendProxy, WandbBackendSpy, spy_proxy

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal


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
from pathlib import Path  # noqa: E402
from queue import Empty, Queue  # noqa: E402

from wandb.sdk.interface.interface_queue import InterfaceQueue  # noqa: E402
from wandb.sdk.internal import context  # noqa: E402
from wandb.sdk.internal.handler import HandleManager  # noqa: E402
from wandb.sdk.internal.sender import SendManager  # noqa: E402
from wandb.sdk.internal.settings_static import SettingsStatic  # noqa: E402
from wandb.sdk.internal.writer import WriteManager  # noqa: E402
from wandb.sdk.lib.mailbox import Mailbox  # noqa: E402


@pytest.fixture()
def internal_result_q():
    return Queue()


@pytest.fixture()
def internal_sender_q():
    return Queue()


@pytest.fixture()
def internal_writer_q():
    return Queue()


@pytest.fixture()
def internal_record_q():
    return Queue()


@pytest.fixture()
def internal_process():
    return MockProcess()


class MockProcess:
    def __init__(self):
        self._alive = True

    def is_alive(self):
        return self._alive


@pytest.fixture()
def _internal_mailbox():
    return Mailbox()


@pytest.fixture()
def _internal_sender(
    internal_record_q, internal_result_q, internal_process, _internal_mailbox
):
    return InterfaceQueue(
        record_q=internal_record_q,
        result_q=internal_result_q,
        process=internal_process,
        mailbox=_internal_mailbox,
    )


@pytest.fixture()
def _internal_context_keeper():
    context_keeper = context.ContextKeeper()
    yield context_keeper


@pytest.fixture()
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


@pytest.fixture()
def stopped_event():
    stopped = threading.Event()
    yield stopped


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
def internal_get_record():
    def _get_record(input_q, timeout=None):
        try:
            i = input_q.get(timeout=timeout)
        except Empty:
            return None
        return i

    return _get_record


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
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


@pytest.fixture()
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


@dataclasses.dataclass(frozen=True)
class LocalWandbBackendAddress:
    _host: str
    _base_port: int
    _fixture_port: int

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._base_port}"

    @property
    def fixture_service_url(self) -> str:
        return f"http://{self._host}:{self._fixture_port}"


@pytest.fixture(scope="session")
def local_wandb_backend() -> LocalWandbBackendAddress:
    """Fixture that starts up or connects to the local-testcontainer.

    This does not patch WANDB_BASE_URL! Use `use_local_wandb_backend` instead.
    """
    return _local_wandb_backend(name="wandb-local-testcontainer")


@pytest.fixture(scope="session")
def local_wandb_backend_importers() -> LocalWandbBackendAddress:
    """Fixture that starts up or connects to a second local-testcontainer.

    This is used by importer tests, to move data between two backends.
    """
    return _local_wandb_backend(name="wandb-local-testcontainer-importers")


def _local_wandb_backend(name: str) -> LocalWandbBackendAddress:
    repo_root = pathlib.Path(__file__).parent.parent.parent
    tool_file = repo_root / "tools" / "local_wandb_server.py"

    result = subprocess.run(
        [
            "python",
            tool_file,
            "connect",
            f"--name={name}",
        ],
        stdout=subprocess.PIPE,
    )

    if result.returncode != 0:
        raise AssertionError(
            "`python tools/local_wandb_server.py connect` failed. See stderr."
            " Did you run `python tools/local_wandb_server.py start`?"
        )

    output = json.loads(result.stdout)
    address = LocalWandbBackendAddress(
        _host="localhost",
        _base_port=int(output["base_port"]),
        _fixture_port=int(output["fixture_port"]),
    )
    return address


@pytest.fixture(scope="function")
def use_local_wandb_backend(
    local_wandb_backend: LocalWandbBackendAddress,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fixture that patches WANDB_BASE_URL to point to the local container.

    Unlike `local_wandb_backend`, this is function-scoped, so cannot be used
    in session-scoped fixtures.
    """
    monkeypatch.setenv("WANDB_BASE_URL", local_wandb_backend.base_url)


def determine_scope(fixture_name, config):
    return config.getoption("--user-scope")


@pytest.fixture(scope="session")
def wandb_verbose(request):
    return request.config.getoption("--wandb-verbose", default=False)


@dataclasses.dataclass
class UserFixtureCommand:
    command: Literal["up", "down", "down_all", "logout", "login", "password"]
    username: Optional[str] = None
    password: Optional[str] = None
    admin: bool = False
    method: Literal["post"] = "post"

    def address(self, addr: LocalWandbBackendAddress) -> str:
        return urllib.parse.urljoin(addr.fixture_service_url, "db/user")


def random_string(length: int = 12) -> str:
    """Generate a random string of a given length.

    :param length: Length of the string to generate.
    :return: Random string.
    """
    return "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length)
    )


@pytest.fixture(scope="session")
def user_factory(worker_id: str):
    def _user_factory(fixture_fn):
        username = f"user-{worker_id}-{random_string()}"
        command = UserFixtureCommand(command="up", username=username)
        fixture_fn(command)
        command = UserFixtureCommand(
            command="password",
            username=username,
            password=username,
        )
        fixture_fn(command)

        with unittest.mock.patch.dict(
            os.environ,
            {
                "WANDB_API_KEY": username,
                "WANDB_ENTITY": username,
                "WANDB_USERNAME": username,
            },
        ):
            yield username

            command = UserFixtureCommand(
                command="down",
                username=username,
            )
            fixture_fn(command)

    yield _user_factory


@pytest.fixture(scope="session")
def fixture_fn_factory():
    def _fixture_fn_factory(address: LocalWandbBackendAddress):
        def fixture_util(cmd: UserFixtureCommand) -> bool:
            endpoint = cmd.address(address)

            if isinstance(cmd, UserFixtureCommand):
                data = {"command": cmd.command}
                if cmd.username:
                    data["username"] = cmd.username
                if cmd.password:
                    data["password"] = cmd.password
                if cmd.admin is not None:
                    data["admin"] = cmd.admin
            else:
                raise NotImplementedError(f"{cmd} is not implemented")

            # trigger fixture
            print(f"Triggering fixture on {endpoint}: {data}", file=sys.stderr)
            response = getattr(requests, cmd.method)(endpoint, json=data)

            if response.status_code != 200:
                print(response.json(), file=sys.stderr)
                return False
            return True

        # todo: remove this once testcontainer is available on Win
        if platform.system() == "Windows":
            pytest.skip("testcontainer is not available on Win")

        yield fixture_util

    yield _fixture_fn_factory


@pytest.fixture(scope="session")
def fixture_fn(fixture_fn_factory, local_wandb_backend):
    yield from fixture_fn_factory(local_wandb_backend)


@pytest.fixture(scope=determine_scope)
def user(user_factory, fixture_fn, use_local_wandb_backend):
    _ = use_local_wandb_backend
    yield from user_factory(fixture_fn)


@pytest.fixture(scope="session")
def wandb_backend_proxy_server(
    local_wandb_backend: LocalWandbBackendAddress,
) -> Generator[WandbBackendProxy, None, None]:
    """Session fixture that starts up a proxy server for the W&B backend."""
    with spy_proxy(
        target_host=local_wandb_backend._host,
        target_port=local_wandb_backend._base_port,
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

    NOTE: This replaces the `relay_server` fixture.

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


@pytest.fixture(scope="function")
def relay_server(wandb_verbose, local_wandb_backend: LocalWandbBackendAddress):
    """A context manager in which the backend is a RelayServer.

    NOTE: This is deprecated. Please use `wandb_backend_spy` instead.

    This returns a context manager that creates a RelayServer and monkey-patches
    WANDB_BASE_URL to point to it.
    """

    @contextmanager
    def relay_server_context(
        inject: Optional[List[InjectedResponse]] = None,
    ) -> Iterator[RelayServer]:
        _relay_server = RelayServer(
            base_url=local_wandb_backend.base_url,
            inject=inject,
            verbose=wandb_verbose,
        )

        _relay_server.start()
        print(f"Relay server started at {_relay_server.relay_url}")

        with unittest.mock.patch.dict(
            os.environ,
            {"WANDB_BASE_URL": _relay_server.relay_url},
        ):
            yield _relay_server

        print(f"Stopping relay server at {_relay_server.relay_url}")

    return relay_server_context


@pytest.fixture(scope="function")
def wandb_init(user, test_settings, request):
    # mirror wandb.sdk.wandb_init.init args, overriding name and entity defaults
    def init(
        job_type: Optional[str] = None,
        dir: Optional[str] = None,
        config: Union[Dict, str, None] = None,
        project: Optional[str] = None,
        entity: Optional[str] = None,
        reinit: bool = None,
        tags: Optional[Sequence] = None,
        group: Optional[str] = None,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        config_exclude_keys: Optional[List[str]] = None,
        config_include_keys: Optional[List[str]] = None,
        anonymous: Optional[str] = None,
        mode: Optional[str] = None,
        allow_val_change: Optional[bool] = None,
        resume: Optional[Union[bool, str]] = None,
        force: Optional[bool] = None,
        tensorboard: Optional[bool] = None,
        sync_tensorboard: Optional[bool] = None,
        monitor_gym: Optional[bool] = None,
        save_code: Optional[bool] = None,
        id: Optional[str] = None,
        fork_from: Optional[str] = None,
        resume_from: Optional[str] = None,
        settings: Union[
            "wandb.sdk.wandb_settings.Settings", Dict[str, Any], None
        ] = None,
    ):
        kwargs = dict(locals())
        # drop fixtures from kwargs
        for key in ("user", "test_settings", "request"):
            kwargs.pop(key, None)
        # merge settings from request with test_settings
        request_settings = kwargs.pop("settings", dict())
        kwargs["name"] = kwargs.pop("name", request.node.name)

        run = wandb.init(
            settings=test_settings(request_settings),
            **kwargs,
        )
        return run

    wandb._IS_INTERNAL_PROCESS = False
    yield init
    # note: this "simulates" a wandb.init function, so you would have to do
    # something like: run = wandb_init(...); ...; run.finish()


@pytest.fixture(scope="function")
def server_context(local_wandb_backend: LocalWandbBackendAddress):
    class ServerContext:
        def __init__(self) -> None:
            self.api = wandb.Api(
                overrides={"base_url": local_wandb_backend.base_url},
            )

        def get_run(self, run: "wandb.sdk.wandb_run.Run") -> "wandb.apis.public.Run":
            return self.api.run(run.path)

    yield ServerContext()


# Injected responses
@pytest.fixture(scope="function")
def inject_file_stream_response(local_wandb_backend, user):
    def helper(
        run,
        body: Union[str, Exception] = "{}",
        status: int = 200,
        application_pattern: str = "1",
    ) -> InjectedResponse:
        if status > 299:
            message = body if isinstance(body, str) else "::".join(body.args)
            body = DeliberateHTTPError(status_code=status, message=message)
        return InjectedResponse(
            method="POST",
            url=(
                urllib.parse.urljoin(
                    local_wandb_backend.base_url,
                    f"/files/{user}/{run.project or 'uncategorized'}/{run.id}/file_stream",
                )
            ),
            body=body,
            status=status,
            application_pattern=TokenizedCircularPattern(application_pattern),
        )

    yield helper


@pytest.fixture(scope="function")
def inject_file_stream_connection_reset(local_wandb_backend, user):
    def helper(
        run,
        body: Union[str, Exception] = "{}",
        status: int = 200,
        application_pattern: str = "1",
    ) -> InjectedResponse:
        return InjectedResponse(
            method="POST",
            url=(
                urllib.parse.urljoin(
                    local_wandb_backend.base_url,
                    f"/files/{user}/{run.project or 'uncategorized'}/{run.id}/file_stream",
                )
            ),
            application_pattern=TokenizedCircularPattern(application_pattern),
            body=body or ConnectionResetError("Connection reset by peer"),
            status=status,
        )

    yield helper


@pytest.fixture(scope="function")
def inject_graphql_response(local_wandb_backend, user):
    def helper(
        body: Union[str, Exception] = "{}",
        status: int = 200,
        query_match_fn=None,
        application_pattern: str = "1",
    ) -> InjectedResponse:
        def match(self, request):
            body = json.loads(request.body)
            return query_match_fn(body["query"], body.get("variables"))

        if status > 299:
            message = body if isinstance(body, str) else "::".join(body.args)
            body = DeliberateHTTPError(status_code=status, message=message)

        return InjectedResponse(
            # request
            method="POST",
            url=urllib.parse.urljoin(local_wandb_backend.base_url, "/graphql"),
            custom_match_fn=match if query_match_fn else None,
            application_pattern=TokenizedCircularPattern(application_pattern),
            # response
            body=body,
            status=status,
        )

    yield helper


@pytest.fixture(scope="function")
def tokenized_circular_pattern():
    return TokenizedCircularPattern
