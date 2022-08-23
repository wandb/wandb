import dataclasses
import json
import logging
import os
import platform
import secrets
import shutil
import socket
import string
import subprocess
import threading
import time
import unittest.mock
import urllib.parse
from collections import defaultdict
from collections.abc import Sequence
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from queue import Empty, Queue
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generator,
    Iterable,
    List,
    Mapping,
    Optional,
    Union,
)

import flask
import git
import pandas as pd
import pytest
import requests
import responses
import wandb
import wandb.old.settings
import wandb.util
from click.testing import CliRunner
from wandb import Api
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.handler import HandleManager
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.lib.git import GitRepo

try:
    from typing import Literal, TypedDict
except ImportError:
    from typing_extensions import Literal, TypedDict

if TYPE_CHECKING:

    class RawRequestResponse(TypedDict):
        url: str
        request: Optional[Any]
        response: Dict[str, Any]
        time_elapsed: float  # seconds

    ResolverName = Literal[
        "upsert_bucket",
        "upload_files",
        "uploaded_files",
        "preempting",
        "upsert_sweep",
    ]

    class Resolver(TypedDict):
        name: ResolverName
        resolver: Callable[[Any], Optional[Dict[str, Any]]]


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
# Misc Fixtures utilities
# --------------------------------


@pytest.fixture
def assets_path() -> Callable:
    def assets_path_fn(path: Path) -> Path:
        return Path(__file__).resolve().parent / "assets" / path

    yield assets_path_fn


@pytest.fixture
def copy_asset(assets_path) -> Callable:
    def copy_asset_fn(
        path: Union[str, Path], dst: Union[str, Path, None] = None
    ) -> Path:
        src = assets_path(path)
        if src.is_file():
            return shutil.copy(src, dst or path)
        return shutil.copytree(src, dst or path)

    yield copy_asset_fn


# --------------------------------
# Misc Fixtures
# --------------------------------


@pytest.fixture(scope="function", autouse=True)
def unset_global_objects():
    from wandb.sdk.lib.module import unset_globals

    yield
    unset_globals()


@pytest.fixture(scope="session", autouse=True)
def env_teardown():
    wandb.teardown()
    yield
    wandb.teardown()
    if not os.environ.get("CI") == "true":
        # TODO: uncomment this for prod? better make controllable with an env var
        # subprocess.run(["wandb", "server", "stop"])
        pass


@pytest.fixture(scope="function", autouse=True)
def clean_up():
    yield
    wandb.teardown()


@pytest.fixture(scope="function", autouse=True)
def filesystem_isolate():
    with CliRunner().isolated_filesystem():
        yield


# todo: this fixture should probably be autouse=True
@pytest.fixture(scope="function", autouse=False)
def local_settings(filesystem_isolate):
    """Place global settings in an isolated dir"""
    config_path = os.path.join(os.getcwd(), ".config", "wandb", "settings")
    wandb.util.mkdir_exists_ok(os.path.join(".config", "wandb"))

    # todo: this breaks things in unexpected places
    # todo: get rid of wandb.old
    with unittest.mock.patch.object(
        wandb.old.settings.Settings,
        "_global_path",
        return_value=config_path,
    ):
        yield


@pytest.fixture(scope="function", autouse=True)
def local_netrc(filesystem_isolate):
    """Never use our real credentials, put them in their own isolated dir"""

    original_expanduser = os.path.expanduser  # TODO: this seems overkill...

    open(".netrc", "wb").close()  # Touch that netrc file

    def expand(path):
        if "netrc" in path:
            try:
                full_path = os.path.realpath("netrc")
            except OSError:
                full_path = original_expanduser(path)
        else:
            full_path = original_expanduser(path)
        return full_path

    # monkeypatch.setattr(os.path, "expanduser", expand)
    with unittest.mock.patch.object(os.path, "expanduser", expand):
        yield


@pytest.fixture
def mocked_ipython(mocker):
    mocker.patch("wandb.sdk.lib.ipython._get_python_type", lambda: "jupyter")
    mocker.patch("wandb.sdk.wandb_settings._get_python_type", lambda: "jupyter")
    html_mock = mocker.MagicMock()
    mocker.patch("wandb.sdk.lib.ipython.display_html", html_mock)
    ipython = unittest.mock.MagicMock()
    ipython.html = html_mock

    def run_cell(cell):
        print("Running cell: ", cell)
        exec(cell)

    ipython.run_cell = run_cell
    # TODO: this is really unfortunate, for reasons not clear to me, monkeypatch doesn't work
    orig_get_ipython = wandb.jupyter.get_ipython
    orig_display = wandb.jupyter.display
    wandb.jupyter.get_ipython = lambda: ipython
    wandb.jupyter.display = lambda obj: html_mock(obj._repr_html_())
    yield ipython
    wandb.jupyter.get_ipython = orig_get_ipython
    wandb.jupyter.display = orig_display


@pytest.fixture
def git_repo(runner):
    with runner.isolated_filesystem(), git.Repo.init(".") as repo:
        wandb.util.mkdir_exists_ok("wandb")
        # Because the forked process doesn't use my monkey patch above
        with open(os.path.join("wandb", "settings"), "w") as f:
            f.write("[default]\nproject: test")
        open("README", "wb").close()
        repo.index.add(["README"])
        repo.index.commit("Initial commit")
        yield GitRepo(lazy=False)


@pytest.fixture
def dummy_api_key():
    return "1824812581259009ca9981580f8f8a9012409eee"


@pytest.fixture
def patch_apikey(dummy_api_key, mocker):
    mocker.patch("wandb.wandb_lib.apikey.isatty", lambda stream: True)
    mocker.patch("wandb.wandb_lib.apikey.input", lambda x: 1)
    mocker.patch("wandb.wandb_lib.apikey.getpass", lambda x: dummy_api_key)
    yield


@pytest.fixture
def patch_prompt(monkeypatch):
    monkeypatch.setattr(
        wandb.util, "prompt_choices", lambda x, input_timeout=None, jupyter=False: x[0]
    )
    monkeypatch.setattr(
        wandb.wandb_lib.apikey,
        "prompt_choices",
        lambda x, input_timeout=None, jupyter=False: x[0],
    )


@pytest.fixture
def runner(patch_apikey, patch_prompt):
    return CliRunner()


@pytest.fixture
def api():
    return Api()


# --------------------------------
# Fixtures for user test point
# --------------------------------


class RecordsUtil:
    def __init__(self, queue: "Queue") -> None:
        self.records = []
        while not queue.empty():
            self.records.append(queue.get())

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, name: str) -> Generator:
        for record in self.records:
            yield from self.resolve_item(record, name)

    @staticmethod
    def resolve_item(obj, attr: str, sep: str = ".") -> List:
        for name in attr.split(sep):
            if not obj.HasField(name):
                return []
            obj = getattr(obj, name)
        return [obj]

    @staticmethod
    def dictify(obj, key: str = "key", value: str = "value_json") -> Dict:
        return {getattr(item, key): getattr(item, value) for item in obj}

    @property
    def config(self) -> List:
        return [self.dictify(_c.update) for _c in self["config"]]

    @property
    def history(self) -> List:
        return [self.dictify(_h.item) for _h in self["history"]]

    @property
    def partial_history(self) -> List:
        return [self.dictify(_h.item) for _h in self["request.partial_history"]]

    @property
    def preempting(self) -> List:
        return list(self["preempting"])

    @property
    def summary(self) -> List:
        return list(self["summary"])

    @property
    def files(self) -> List:
        return list(self["files"])

    @property
    def metric(self):
        return list(self["metric"])


@pytest.fixture
def parse_records() -> Generator[Callable, None, None]:
    def records_parser_fn(q: "Queue") -> RecordsUtil:
        return RecordsUtil(q)

    yield records_parser_fn


@pytest.fixture()
def record_q() -> "Queue":
    return Queue()


@pytest.fixture()
def mocked_interface(record_q: "Queue") -> InterfaceQueue:
    return InterfaceQueue(record_q=record_q)


@pytest.fixture
def mocked_backend(mocked_interface: InterfaceQueue) -> Generator[object, None, None]:
    class MockedBackend:
        def __init__(self) -> None:
            self.interface = mocked_interface

    yield MockedBackend()


@pytest.fixture(scope="function")
def mock_run(test_settings, mocked_backend) -> Generator[Callable, None, None]:
    from wandb.sdk.lib.module import unset_globals

    def mock_run_fn(use_magic_mock=False, **kwargs: Any) -> "wandb.sdk.wandb_run.Run":
        kwargs_settings = kwargs.pop("settings", dict())
        kwargs_settings = {
            **{
                "run_id": wandb.util.generate_id(),
            },
            **kwargs_settings,
        }
        run = wandb.wandb_sdk.wandb_run.Run(
            settings=test_settings(kwargs_settings), **kwargs
        )
        run._set_backend(
            unittest.mock.MagicMock() if use_magic_mock else mocked_backend
        )
        run._set_globals()
        return run

    yield mock_run_fn
    unset_globals()


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
def _internal_sender(internal_record_q, internal_result_q, internal_process):
    return InterfaceQueue(
        record_q=internal_record_q,
        result_q=internal_result_q,
        process=internal_process,
    )


@pytest.fixture()
def internal_sm(
    runner,
    internal_sender_q,
    internal_result_q,
    _internal_sender,
):
    def helper(settings):
        with runner.isolated_filesystem():
            sm = SendManager(
                settings=SettingsStatic(settings.make_static()),
                record_q=internal_sender_q,
                result_q=internal_result_q,
                interface=_internal_sender,
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
    internal_sender_q,
    internal_writer_q,
    _internal_sender,
    stopped_event,
):
    def helper(settings):
        with runner.isolated_filesystem():
            hm = HandleManager(
                settings=SettingsStatic(settings.make_static()),
                record_q=internal_record_q,
                result_q=internal_result_q,
                stopped=stopped_event,
                sender_q=internal_sender_q,
                writer_q=internal_writer_q,
                interface=_internal_sender,
            )
            return hm

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
    _internal_sender,
    start_handle_thread,
    start_send_thread,
):
    def start_backend_func(run=None, initial_run=True, initial_start=True):
        ihm = internal_hm(run.settings)
        ism = internal_sm(run.settings)
        ht = start_handle_thread(ihm)
        st = start_send_thread(ism)
        if initial_run:
            _run = _internal_sender.communicate_run(run)
            if initial_start:
                _internal_sender.communicate_run_start(_run.run)
        return ht, st

    yield start_backend_func


@pytest.fixture()
def _stop_backend(
    _internal_sender,
    # collect_responses,
):
    def stop_backend_func(threads=None):
        threads = threads or ()
        done = False
        _internal_sender.publish_exit(0)
        for _ in range(30):
            poll_exit_resp = _internal_sender.communicate_poll_exit()
            if poll_exit_resp:
                done = poll_exit_resp.done
                if done:
                    # collect_responses.local_info = poll_exit_resp.local_info
                    break
            time.sleep(1)
        _internal_sender.join()
        for t in threads:
            t.join()
        assert done, "backend didn't shut down"

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
        default="http://localhost:8080",
        help='cli to set "base-url"',
    )
    parser.addoption(
        "--wandb-server-tag",
        default="master",
        help="Image tag to use for the wandb server",
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
    """
    Generate a random string of a given length.
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
def wandb_debug(request):
    return request.config.getoption("--wandb-debug", default=False)


def check_server_health(
    base_url: str, endpoint: str, num_retries: int = 1, sleep_time: int = 1
) -> bool:
    """
    Check if wandb server is healthy.
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


def check_mysql_health(num_retries: int = 1, sleep_time: int = 1):
    for _ in range(num_retries):
        try:
            exit_code = subprocess.call(
                [
                    "docker",
                    "exec",
                    "-t",
                    "wandb-local",
                    "/bin/bash",
                    "-c",
                    "sudo mysqladmin ping",
                ]
            )
            if exit_code == 0:
                return True
            time.sleep(sleep_time)
        except subprocess.CalledProcessError:
            time.sleep(sleep_time)
    return False


def check_server_up(
    base_url: str,
    wandb_server_tag: str = "master",
) -> bool:
    """
    Check if wandb server is up and running;
    if not on the CI and the server is not running, then start it first.
    :param base_url:
    :param wandb_server_tag:
    :return:
    """
    # breakpoint()
    app_health_endpoint = "healthz"
    fixture_url = base_url.replace("8080", "9003")
    fixture_health_endpoint = "health"

    if os.environ.get("CI") == "true":
        return check_server_health(base_url=base_url, endpoint=app_health_endpoint)

    if not check_server_health(base_url=base_url, endpoint=app_health_endpoint):
        # start wandb server locally and expose ports 8080, 8083, and 9003
        command = [
            "docker",
            "run",
            "--rm",
            "-v",
            "wandb:/vol",
            "-p",
            "8080:8080",
            "-p",
            "8083:8083",
            "-p",
            "9003:9003",
            "-e",
            "WANDB_ENABLE_TEST_CONTAINER=true",
            "--name",
            "wandb-local",
            f"gcr.io/wandb-production/local-testcontainer:{wandb_server_tag}",
        ]
        subprocess.Popen(command)
        # wait for the server to start
        server_is_up = check_server_health(
            base_url=base_url, endpoint=app_health_endpoint, num_retries=30
        )
        if not server_is_up:
            return False
        # check that MySQL and fixture service are accessible
        return check_mysql_health(num_retries=30) and check_server_health(
            base_url=fixture_url, endpoint=fixture_health_endpoint, num_retries=30
        )

    return check_mysql_health(num_retries=10) and check_server_health(
        base_url=fixture_url, endpoint=fixture_health_endpoint, num_retries=10
    )


@dataclasses.dataclass
class UserFixtureCommand:
    command: Literal["up", "down", "down_all", "logout", "login"]
    username: Optional[str] = None
    admin: bool = False
    endpoint: str = "db/user"
    port: int = 9003
    method: Literal["post"] = "post"


@dataclasses.dataclass
class AddAdminAndEnsureNoDefaultUser:
    email: str
    password: str
    endpoint: str = "api/users-admin"
    port: int = 8083
    method: Literal["put"] = "put"


@pytest.fixture(scope="session")
def fixture_fn(base_url, wandb_server_tag):
    def fixture_util(
        cmd: Union[UserFixtureCommand, AddAdminAndEnsureNoDefaultUser]
    ) -> bool:
        endpoint = urllib.parse.urljoin(
            base_url.replace("8080", str(cmd.port)),
            cmd.endpoint,
        )

        if isinstance(cmd, UserFixtureCommand):
            data = {"command": cmd.command}
            if cmd.username:
                data["username"] = cmd.username
            if cmd.admin is not None:
                data["admin"] = cmd.admin
        elif isinstance(cmd, AddAdminAndEnsureNoDefaultUser):
            data = [
                {"email": f"{cmd.email}@wandb.com", "password": cmd.password},
                {"email": "local@wandb.com", "delete": True},
            ]
        else:
            raise NotImplementedError(f"{cmd} is not implemented")
        # trigger fixture
        print(f"Triggering fixture: {data}")
        response = getattr(requests, cmd.method)(endpoint, json=data)
        if response.status_code != 200:
            print(response.json())
            return False
        return True

    # todo: remove this once testcontainer is available on Win
    if platform.system() == "Windows":
        pytest.skip("testcontainer is not available on Win")

    if not check_server_up(base_url, wandb_server_tag):
        pytest.fail("wandb server is not running")

    yield fixture_util


@pytest.fixture(scope=determine_scope)
def user(worker_id: str, fixture_fn, base_url, wandb_debug) -> str:
    username = f"user-{worker_id}-{random_string()}"
    command = UserFixtureCommand(command="up", username=username)
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
        command = UserFixtureCommand(
            command="up",
            username=admin_username,
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


class DeliberateHTTPError(Exception):
    def __init__(self, message, status_code: int = 500):
        Exception.__init__(self)
        self.message = message
        self.status_code = status_code

    def get_response(self):
        return flask.Response(self.message, status=self.status_code)

    def __repr__(self):
        return f"DeliberateHTTPError({self.message!r}, {self.status_code!r})"


class Timer:
    def __init__(self) -> None:
        self.start: float = time.perf_counter()
        self.stop: float = self.start

    def __enter__(self) -> "Timer":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return self.stop - self.start


class Context:
    """
    Implements a container used to store the snooped state/data of a test,
    including raw requests and responses; parsed and processed data; and
    a number of convenience methods and properties for accessing the data.
    """

    def __init__(self) -> None:
        # parsed/merged data. keys are the individual wandb run id's.
        self._entries = defaultdict(dict)
        # container for raw requests and responses:
        self.raw_data: List["RawRequestResponse"] = []
        # concatenated file contents for all runs:
        self._history: Optional[pd.DataFrame] = None
        self._events: Optional[pd.DataFrame] = None
        self._summary: Optional[pd.DataFrame] = None
        self._config: Optional[Dict[str, Any]] = None

    @classmethod
    def _merge(
        cls, source: Dict[str, Any], destination: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Recursively merge two dictionaries.
        """
        for key, value in source.items():
            if isinstance(value, dict):
                # get node or create one
                node = destination.setdefault(key, {})
                cls._merge(value, node)
            else:
                if isinstance(value, list):
                    if key in destination:
                        destination[key].extend(value)
                    else:
                        destination[key] = value
                else:
                    destination[key] = value
        return destination

    def upsert(self, entry: Dict[str, Any]) -> None:
        entry_id: str = entry["name"]
        self._entries[entry_id] = self._merge(entry, self._entries[entry_id])

    # mapping interface
    def __getitem__(self, key: str) -> Any:
        return self._entries[key]

    def keys(self) -> Iterable[str]:
        return self._entries.keys()

    def get_file_contents(self, file_name: str) -> pd.DataFrame:
        dfs = []

        for entry_id in self._entries:
            # - extract the content from `file_name`
            # - sort by offset (will be useful when relay server goes async)
            # - extract data, merge into a list of dicts and convert to a pandas dataframe
            content_list = self._entries[entry_id].get("files", {}).get(file_name, [])
            content_list.sort(key=lambda x: x["offset"])
            content_list = [item["content"] for item in content_list]
            # merge list of lists content_list:
            content_list = [item for sublist in content_list for item in sublist]
            df = pd.DataFrame.from_records(content_list)
            df["__run_id"] = entry_id
            dfs.append(df)

        return pd.concat(dfs)

    # attributes to use in assertions
    @property
    def entries(self) -> Dict[str, Any]:
        return deepcopy(self._entries)

    @property
    def history(self) -> pd.DataFrame:
        # todo: caveat: this assumes that all assertions happen at the end of a test
        if self._history is not None:
            return deepcopy(self._history)

        self._history = self.get_file_contents("wandb-history.jsonl")
        return deepcopy(self._history)

    @property
    def events(self) -> pd.DataFrame:
        if self._events is not None:
            return deepcopy(self._events)

        self._events = self.get_file_contents("wandb-events.jsonl")
        return deepcopy(self._events)

    @property
    def summary(self) -> pd.DataFrame:
        if self._summary is not None:
            return deepcopy(self._summary)

        _summary = self.get_file_contents("wandb-summary.json")

        # run summary may be updated multiple times,
        # but we are only interested in the last one.
        # we can have multiple runs saved to context,
        # so we need to group by run id and take the
        # last one for each run.
        self._summary = (
            _summary.groupby("__run_id").last().reset_index(level=["__run_id"])
        )

        return deepcopy(self._summary)

    @property
    def config(self) -> Dict[str, Any]:
        if self._config is not None:
            return deepcopy(self._config)

        self._config = {k: v["config"] for (k, v) in self._entries.items()}
        return deepcopy(self._config)

    # @property
    # def telemetry(self) -> pd.DataFrame:
    #     telemetry = pd.DataFrame.from_records(
    #         [
    #             {
    #                 "__run_id": run_id,
    #                 "telemetry": config.get("_wandb", {}).get("value", {}).get("t")
    #             }
    #             for (run_id, config) in self.config.items()
    #         ]
    #     )
    #     return telemetry

    # convenience data access methods
    def get_run_telemetry(self, run_id: str) -> Dict[str, Any]:
        return self.config.get(run_id, {}).get("_wandb", {}).get("value", {}).get("t")

    def get_run_metrics(self, run_id: str) -> Dict[str, Any]:
        return self.config.get(run_id, {}).get("_wandb", {}).get("value", {}).get("m")

    def get_run_summary(
        self, run_id: str, include_private: bool = False
    ) -> Dict[str, Any]:
        # run summary dataframe must have only one row
        # for the given run id, so we convert it to dict
        # and extract the first (and only) row.
        mask_run = self.summary["__run_id"] == run_id
        run_summary = self.summary[mask_run]
        ret = (
            run_summary.filter(regex="^[^_]", axis=1)
            if not include_private
            else run_summary
        ).to_dict(orient="records")
        return ret[0] if len(ret) > 0 else {}

    def get_run_history(
        self, run_id: str, include_private: bool = False
    ) -> pd.DataFrame:
        mask_run = self.history["__run_id"] == run_id
        run_history = self.history[mask_run]
        return (
            run_history.filter(regex="^[^_]", axis=1)
            if not include_private
            else run_history
        )

    def get_run_uploaded_files(self, run_id: str) -> Dict[str, Any]:
        return self.entries.get(run_id, {}).get("uploaded", [])

    def get_run_stats(self, run_id: str) -> pd.DataFrame:
        mask_run = self.events["__run_id"] == run_id
        run_stats = self.events[mask_run]
        return run_stats

    # todo: add getter (by run_id) utilities for other properties


class QueryResolver:
    """
    Resolves request/response pairs against a set of known patterns
    to extract and process useful data, to be later stored in a Context object.
    """

    def __init__(self):
        self.resolvers: List["Resolver"] = [
            {
                "name": "upsert_bucket",
                "resolver": self.resolve_upsert_bucket,
            },
            {
                "name": "upload_files",
                "resolver": self.resolve_upload_files,
            },
            {
                "name": "uploaded_files",
                "resolver": self.resolve_uploaded_files,
            },
            {
                "name": "preempting",
                "resolver": self.resolve_preempting,
            },
            {
                "name": "upsert_sweep",
                "resolver": self.resolve_upsert_sweep,
            },
            # { "name": "create_artifact",
            #     "resolver": self.resolve_create_artifact,
            # },
        ]

    @staticmethod
    def resolve_upsert_bucket(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict) or not isinstance(response_data, dict):
            return None
        query = response_data.get("data", {}).get("upsertBucket") is not None
        if query:
            data = response_data["data"]["upsertBucket"].get("bucket")
            data["config"] = json.loads(data["config"])
            return data
        return None

    @staticmethod
    def resolve_upload_files(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict):
            return None
        query = request_data.get("files") is not None
        if query:
            # todo: refactor this 🤮🤮🤮🤮🤮 eventually?
            name = kwargs.get("path").split("/")[2]
            files = {
                file_name: [
                    {
                        "content": [
                            json.loads(k) for k in file_value.get("content", [])
                        ],
                        "offset": file_value.get("offset"),
                    }
                ]
                for file_name, file_value in request_data["files"].items()
            }
            post_processed_data = {
                "name": name,
                "dropped": [request_data["dropped"]],
                "files": files,
            }
            return post_processed_data
        return None

    @staticmethod
    def resolve_uploaded_files(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict) or not isinstance(response_data, dict):
            return None
        query = "RunUploadUrls" in request_data.get("query", "")
        if query:
            # todo: refactor this 🤮🤮🤮🤮🤮 eventually?
            name = request_data["variables"]["run"]
            files = (
                response_data.get("data", {})
                .get("model", {})
                .get("bucket", {})
                .get("files", {})
                .get("edges", [])
            )
            # note: we count all attempts to upload files
            post_processed_data = {
                "name": name,
                "uploaded": [files[0].get("node", {}).get("name")] if files else [""],
            }
            return post_processed_data
        return None

    @staticmethod
    def resolve_preempting(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict):
            return None
        query = "preempting" in request_data
        if query:
            name = kwargs.get("path").split("/")[2]
            post_processed_data = {
                "name": name,
                "preempting": [request_data["preempting"]],
            }
            return post_processed_data
        return None

    @staticmethod
    def resolve_upsert_sweep(
        request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(response_data, dict):
            return None
        query = response_data.get("data", {}).get("upsertSweep") is not None
        if query:
            data = response_data["data"]["upsertSweep"].get("sweep")
            return data
        return None

    def resolve_create_artifact(
        self, request_data: Dict[str, Any], response_data: Dict[str, Any], **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(request_data, dict):
            return None
        query = (
            "createArtifact(" in request_data.get("query", "")
            and request_data.get("variables") is not None
            and response_data is not None
        )
        if query:
            name = request_data["variables"]["runName"]
            post_processed_data = {
                "name": name,
                "create_artifact": [
                    {
                        "variables": request_data["variables"],
                        "response": response_data["data"]["createArtifact"]["artifact"],
                    }
                ],
            }
            return post_processed_data
        return None

    def resolve(
        self,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        for resolver in self.resolvers:
            result = resolver.get("resolver")(request_data, response_data, **kwargs)
            if result is not None:
                return result
        return None


@dataclasses.dataclass
class InjectedResponse:
    method: str
    url: str
    body: Union[str, Exception]
    # json: Optional[Dict[str, Any]] = None
    status: int = 200
    content_type: str = "text/plain"
    # todo: add more fields for other types of responses?
    counter: int = -1

    def __eq__(
        self,
        other: Union["InjectedResponse", requests.Request, requests.PreparedRequest],
    ):
        """
        Equality check for InjectedResponse objects.
        We use this to check if this response should be injected as a replacement of `other`.

        :param other:
        :return:
        """
        if not isinstance(
            other, (InjectedResponse, requests.Request, requests.PreparedRequest)
        ):
            return False
        if self.counter == 0:
            return False
        # todo: add more fields for other types of responses?
        return self.method == other.method and self.url == other.url

    def to_dict(self):
        return {
            k: self.__getattribute__(k)
            for k in self.__dict__
            if (not k.startswith("_") and k != "counter")
        }


class RelayServer:
    def __init__(
        self,
        base_url: str,
        inject: Optional[List[InjectedResponse]] = None,
    ) -> None:
        # todo for the future:
        #  - consider switching from Flask to Quart
        #  - async app will allow for better failure injection/poor network perf
        self.app = flask.Flask(__name__)
        self.app.logger.setLevel(logging.INFO)
        self.app.register_error_handler(DeliberateHTTPError, self.handle_http_exception)
        self.app.add_url_rule(
            rule="/graphql",
            endpoint="graphql",
            view_func=self.graphql,
            methods=["POST"],
        )
        self.app.add_url_rule(
            rule="/files/<path:path>",
            endpoint="files",
            view_func=self.file_stream,
            methods=["POST"],
        )
        self.app.add_url_rule(
            rule="/storage",
            endpoint="storage",
            view_func=self.storage,
            methods=["PUT", "GET"],
        )
        self.app.add_url_rule(
            rule="/storage/<path:path>",
            endpoint="storage_file",
            view_func=self.storage_file,
            methods=["PUT", "GET"],
        )
        # @app.route("/artifacts/<entity>/<digest>", methods=["GET", "POST"])
        self.port = self._get_free_port()
        self.base_url = urllib.parse.urlparse(base_url)
        self.session = requests.Session()
        self.relay_url = f"http://127.0.0.1:{self.port}"

        # recursively merge-able object to store state
        self.resolver = QueryResolver()
        self.context = Context()

        # injected responses
        self.inject = inject or []

        # useful when debugging:
        # self.after_request_fn = self.app.after_request(self.after_request_fn)

    @staticmethod
    def handle_http_exception(e):
        response = e.get_response()
        return response

    @staticmethod
    def _get_free_port() -> int:
        sock = socket.socket()
        sock.bind(("", 0))

        _, port = sock.getsockname()
        return port

    def start(self) -> None:
        # run server in a separate thread
        relay_server_thread = threading.Thread(
            target=self.app.run,
            kwargs={"port": self.port},
            daemon=True,
        )
        relay_server_thread.start()

    def after_request_fn(self, response: "requests.Response") -> "requests.Response":
        # todo: this is useful for debugging, but should be removed in the future
        # flask.request.url = self.relay_url + flask.request.url
        print(flask.request)
        print(flask.request.get_json())
        print(response)
        print(response.json())
        return response

    def relay(
        self,
        request: "flask.Request",
    ) -> Union["responses.Response", "requests.Response"]:
        # replace the relay url with the real backend url (self.base_url)
        url = (
            urllib.parse.urlparse(request.url)
            ._replace(netloc=self.base_url.netloc)
            .geturl()
        )
        headers = {key: value for (key, value) in request.headers if key != "Host"}
        prepared_relayed_request = requests.Request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            json=request.get_json(),
        ).prepare()

        for injected_response in self.inject:
            # check if an injected response matches the request
            if injected_response == prepared_relayed_request:
                with responses.RequestsMock() as mocked_responses:
                    # do the actual injection
                    mocked_responses.add(**injected_response.to_dict())
                    # ensure we don't apply this more times than requested
                    injected_response.counter -= 1
                    relayed_response = self.session.send(prepared_relayed_request)

                    return relayed_response

        # normal case: no injected response matches the request
        relayed_response = self.session.send(prepared_relayed_request)
        return relayed_response

    def snoop_context(
        self,
        request: "flask.Request",
        response: "requests.Response",
        time_elapsed: float,
        **kwargs: Any,
    ) -> None:
        request_data = request.get_json()
        response_data = response.json() or {}

        # store raw data
        raw_data: "RawRequestResponse" = {
            "url": request.url,
            "request": request_data,
            "response": response_data,
            "time_elapsed": time_elapsed,
        }
        self.context.raw_data.append(raw_data)

        snooped_context = self.resolver.resolve(request_data, response_data, **kwargs)
        if snooped_context is not None:
            self.context.upsert(snooped_context)

        return None

    def graphql(self) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        # print("*****************")
        # print("GRAPHQL REQUEST:")
        # print(request.get_json())
        # print("GRAPHQL RESPONSE:")
        # print(relayed_response.status_code, relayed_response.json())
        # print("*****************")
        # snoop work to extract the context
        self.snoop_context(request, relayed_response, timer.elapsed)
        # print("*****************")
        # print("SNOOPED CONTEXT:")
        # print(self.context.entries)
        # print(len(self.context.raw_data))
        # print("*****************")

        return relayed_response.json()

    def file_stream(self, path) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        # print("*****************")
        # print("FILE STREAM REQUEST:")
        # print("********PATH*********")
        # print(path)
        # print("********ENDPATH*********")
        # print(request.get_json())
        # print("FILE STREAM RESPONSE:")
        # print(relayed_response)
        # print(relayed_response.status_code, relayed_response.json())
        # print("*****************")

        self.snoop_context(request, relayed_response, timer.elapsed, path=path)

        return relayed_response.json()

    def storage(self) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        # print("*****************")
        # print("STORAGE REQUEST:")
        # print(request.get_json())
        # print("STORAGE RESPONSE:")
        # print(relayed_response.status_code, relayed_response.json())
        # print("*****************")

        self.snoop_context(request, relayed_response, timer.elapsed)

        return relayed_response.json()

    def storage_file(self, path) -> Mapping[str, str]:
        request = flask.request
        with Timer() as timer:
            relayed_response = self.relay(request)
        # print("*****************")
        # print("STORAGE FILE REQUEST:")
        # print("********PATH*********")
        # print(path)
        # print("********ENDPATH*********")
        # print(request.get_json())
        # print("STORAGE FILE RESPONSE:")
        # print(relayed_response.json())
        # print("*****************")

        self.snoop_context(request, relayed_response, timer.elapsed, path=path)

        return relayed_response.json()


@pytest.fixture(scope="function")
def relay_server(base_url):
    """
    Creates a new relay server.
    """

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


def dict_factory():
    def helper():
        return dict()

    return helper


@pytest.fixture(scope="function")
def test_settings():
    def update_test_settings(
        extra_settings: Union[
            dict, wandb.sdk.wandb_settings.Settings
        ] = dict_factory()  # noqa: B008
    ):
        settings = wandb.Settings(
            console="off",
            save_code=False,
        )
        if isinstance(extra_settings, dict):
            settings.update(extra_settings, source=wandb.sdk.wandb_settings.Source.BASE)
        elif isinstance(extra_settings, wandb.sdk.wandb_settings.Settings):
            settings.update(extra_settings)
        settings._set_run_start_time()
        return settings

    yield update_test_settings


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
        counter: int = -1,
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
            counter=counter,
        )

    yield helper
