import dataclasses
import os
import platform
import secrets
import string
import subprocess
import threading
import time
import unittest.mock
import urllib.parse
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, List, Optional, Union

import pytest
import requests
import wandb
import wandb.old.settings
import wandb.util
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import context
from wandb.sdk.internal.handler import HandleManager
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.writer import WriteManager
from wandb.sdk.lib.mailbox import Mailbox
from wandb.testing.relay import (
    DeliberateHTTPError,
    InjectedResponse,
    RelayServer,
    TokenizedCircularPattern,
)

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


# `local-testcontainer` ports
LOCAL_BASE_PORT = "8080"
SERVICES_API_PORT = "8083"
FIXTURE_SERVICE_PORT = "9015"


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


# --------------------------------
# Fixtures for internal test point
# --------------------------------


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
                settings=SettingsStatic(settings.make_static()),
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
                settings=SettingsStatic(settings.make_static()),
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

            # this is hacky, but we dont have a clean rundir always
            # so lets at least make sure we can write to this dir
            run_dir = Path(wandb_file).parent
            os.makedirs(run_dir)

            wm = WriteManager(
                settings=SettingsStatic(settings.make_static()),
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
            _run = _internal_sender.communicate_run(run)
            if initial_start:
                _internal_sender.communicate_run_start(_run.run)
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
        record = handle.wait(timeout=30)
        assert record

        server_info_handle = _internal_sender.deliver_request_server_info()
        result = server_info_handle.wait(timeout=30)
        assert result
        # collect_responses.server_info_resp = result.response.server_info_response

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


def pytest_addoption(parser):
    # note: we default to "function" scope to ensure the environment is
    # set up properly when running the tests in parallel with pytest-xdist.
    parser.addoption(
        "--user-scope",
        default="function",  # or "function" or "session" or "module"
        help='cli to set scope of fixture "user-scope"',
    )
    parser.addoption(
        "--base-url",
        default=f"http://localhost:{LOCAL_BASE_PORT}",
        help='cli to set "base-url"',
    )
    parser.addoption(
        "--wandb-server-tag",
        default="master",
        help="Image tag to use for the wandb server",
    )
    parser.addoption(
        "--wandb-server-pull",
        action="store_true",
        default=False,
        help="Force pull the latest wandb server image",
    )
    # debug option: creates an admin account that can be used to log in to the
    # app and inspect the test runs.
    parser.addoption(
        "--wandb-debug",
        action="store_true",
        default=False,
        help="Run tests in debug mode",
    )


def random_string(length: int = 12) -> str:
    """Generate a random string of a given length.

    :param length: Length of the string to generate.
    :return: Random string.
    """
    return "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length)
    )


def determine_scope(fixture_name, config):
    return config.getoption("--user-scope")


@pytest.fixture(scope="session")
def base_url(request):
    return request.config.getoption("--base-url")


@pytest.fixture(scope="session")
def wandb_server_tag(request):
    return request.config.getoption("--wandb-server-tag")


@pytest.fixture(scope="session")
def wandb_server_pull(request):
    if request.config.getoption("--wandb-server-pull"):
        return "always"
    return "missing"


@pytest.fixture(scope="session")
def wandb_debug(request):
    return request.config.getoption("--wandb-debug", default=False)


def check_server_health(
    base_url: str, endpoint: str, num_retries: int = 1, sleep_time: int = 1
) -> bool:
    """Check if wandb server is healthy.

    :param base_url:
    :param num_retries:
    :param sleep_time:
    :return:
    """
    for _ in range(num_retries):
        try:
            response = requests.get(urllib.parse.urljoin(base_url, endpoint))
            if response.status_code == 200:
                return True
            time.sleep(sleep_time)
        except requests.exceptions.ConnectionError:
            time.sleep(sleep_time)
    return False


def check_server_up(
    base_url: str,
    wandb_server_tag: str = "master",
    wandb_server_pull: Literal["missing", "always"] = "missing",
) -> bool:
    """Check if wandb server is up and running.

    If not on the CI and the server is not running, then start it first.

    :param base_url:
    :param wandb_server_tag:
    :param wandb_server_pull:
    :return:
    """
    app_health_endpoint = "healthz"
    fixture_url = base_url.replace(LOCAL_BASE_PORT, FIXTURE_SERVICE_PORT)
    fixture_health_endpoint = "health"

    if os.environ.get("CI") == "true":
        return check_server_health(base_url=base_url, endpoint=app_health_endpoint)

    if not check_server_health(base_url=base_url, endpoint=app_health_endpoint):
        # start wandb server locally and expose necessary ports to the host
        command = [
            "docker",
            "run",
            "--pull",
            wandb_server_pull,
            "--rm",
            "-v",
            "wandb:/vol",
            "-p",
            f"{LOCAL_BASE_PORT}:{LOCAL_BASE_PORT}",
            "-p",
            f"{SERVICES_API_PORT}:{SERVICES_API_PORT}",
            "-p",
            f"{FIXTURE_SERVICE_PORT}:{FIXTURE_SERVICE_PORT}",
            "-e",
            "WANDB_ENABLE_TEST_CONTAINER=true",
            "--name",
            "wandb-local",
            "--platform",
            "linux/amd64",
            f"us-central1-docker.pkg.dev/wandb-production/images/local-testcontainer:{wandb_server_tag}",
        ]
        subprocess.Popen(command)
        # wait for the server to start
        server_is_up = check_server_health(
            base_url=base_url, endpoint=app_health_endpoint, num_retries=30
        )
        if not server_is_up:
            return False
        # check that the fixture service is accessible
        return check_server_health(
            base_url=fixture_url, endpoint=fixture_health_endpoint, num_retries=30
        )

    return check_server_health(
        base_url=fixture_url, endpoint=fixture_health_endpoint, num_retries=10
    )


@dataclasses.dataclass
class UserFixtureCommand:
    command: Literal["up", "down", "down_all", "logout", "login", "password"]
    username: Optional[str] = None
    password: Optional[str] = None
    admin: bool = False
    endpoint: str = "db/user"
    port: str = FIXTURE_SERVICE_PORT
    method: Literal["post"] = "post"


@dataclasses.dataclass
class AddAdminAndEnsureNoDefaultUser:
    email: str
    password: str
    endpoint: str = "api/users-admin"
    port: str = SERVICES_API_PORT
    method: Literal["put"] = "put"


@pytest.fixture(scope="session")
def fixture_fn(base_url, wandb_server_tag, wandb_server_pull):
    def fixture_util(
        cmd: Union[UserFixtureCommand, AddAdminAndEnsureNoDefaultUser]
    ) -> bool:
        endpoint = urllib.parse.urljoin(
            base_url.replace(LOCAL_BASE_PORT, cmd.port),
            cmd.endpoint,
        )

        if isinstance(cmd, UserFixtureCommand):
            data = {"command": cmd.command}
            if cmd.username:
                data["username"] = cmd.username
            if cmd.password:
                data["password"] = cmd.password
            if cmd.admin is not None:
                data["admin"] = cmd.admin
        elif isinstance(cmd, AddAdminAndEnsureNoDefaultUser):
            data = [
                {"email": f"{cmd.email}@wandb.com", "password": cmd.password},
            ]
        else:
            raise NotImplementedError(f"{cmd} is not implemented")
        # trigger fixture
        print(f"Triggering fixture on {endpoint}: {data}")
        response = getattr(requests, cmd.method)(endpoint, json=data)
        if response.status_code != 200:
            print(response.json())
            return False
        return True

    # todo: remove this once testcontainer is available on Win
    if platform.system() == "Windows":
        pytest.skip("testcontainer is not available on Win")

    if not check_server_up(base_url, wandb_server_tag, wandb_server_pull):
        pytest.fail("wandb server is not running")

    yield fixture_util


@pytest.fixture(scope=determine_scope)
def user(worker_id: str, fixture_fn, base_url, wandb_debug) -> str:
    username = f"user-{worker_id}-{random_string()}"
    command = UserFixtureCommand(command="up", username=username)
    fixture_fn(command)
    command = UserFixtureCommand(
        command="password", username=username, password=username
    )
    fixture_fn(command)

    with unittest.mock.patch.dict(
        os.environ,
        {
            "WANDB_API_KEY": username,
            "WANDB_ENTITY": username,
            "WANDB_USERNAME": username,
            "WANDB_BASE_URL": base_url,
        },
    ):
        yield username

        if not wandb_debug:
            command = UserFixtureCommand(command="down", username=username)
            fixture_fn(command)


@pytest.fixture(scope="session", autouse=True)
def debug(wandb_debug, fixture_fn, base_url):
    if wandb_debug:
        admin_username = f"admin-{random_string()}"
        # disable default user and create an admin account that can be used to log in to the app
        # and inspect the test runs.
        command = UserFixtureCommand(command="down", username="local@wandb.com")
        fixture_fn(command)
        command = UserFixtureCommand(
            command="up",
            username=admin_username,
            admin=True,
        )
        fixture_fn(command)

        command = UserFixtureCommand(
            command="password",
            username=admin_username,
            password=admin_username,
            admin=True,
        )
        fixture_fn(command)

        command = AddAdminAndEnsureNoDefaultUser(
            email=admin_username,
            password=admin_username,
        )
        fixture_fn(command)
        message = (
            f"{ConsoleFormatter.GREEN}"
            "*****************************************************************\n"
            "Admin user created for debugging:\n"
            f"Proceed to {base_url} and log in with the following credentials:\n"
            f"username: {admin_username}@wandb.com\n"
            f"password: {admin_username}\n"
            "*****************************************************************"
            f"{ConsoleFormatter.END}"
        )
        print(message)
        yield admin_username
        print(message)
        # input("\nPress any key to exit...")
        # command = UserFixtureCommand(command="down_all")
        # fixture_fn(command)
    else:
        yield None


@pytest.fixture(scope="function")
def relay_server(base_url):
    """Create a new relay server."""

    @contextmanager
    def relay_server_context(inject: Optional[List[InjectedResponse]] = None):
        _relay_server = RelayServer(base_url=base_url, inject=inject)
        try:
            _relay_server.start()
            print(f"Relay server started at {_relay_server.relay_url}")
            with unittest.mock.patch.dict(
                os.environ,
                {"WANDB_BASE_URL": _relay_server.relay_url},
            ):
                yield _relay_server
            print(f"Stopping relay server at {_relay_server.relay_url}")
        finally:
            del _relay_server

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
        magic: Union[dict, str, bool] = None,
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
def server_context(base_url):
    class ServerContext:
        def __init__(self) -> None:
            self.api = wandb.Api(overrides={"base_url": base_url})

        def get_run(self, run: "wandb.sdk.wandb_run.Run") -> "wandb.apis.public.Run":
            return self.api.run(run.path)

    yield ServerContext()


# Injected responses
@pytest.fixture(scope="function")
def inject_file_stream_response(base_url, user):
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
                    base_url,
                    f"/files/{user}/{run.project or 'uncategorized'}/{run.id}/file_stream",
                )
            ),
            body=body,
            status=status,
            application_pattern=TokenizedCircularPattern(application_pattern),
        )

    yield helper
