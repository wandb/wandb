import os
import shutil
import sys
import threading
import unittest.mock
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Union,
)

import git
import pytest
import responses
import wandb
import wandb.old.settings
import wandb.util
from click.testing import CliRunner
from wandb import Api
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import context
from wandb.sdk.internal.handler import HandleManager
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.writer import WriteManager
from wandb.sdk.lib import filesystem, runid
from wandb.sdk.lib.git import GitRepo
from wandb.sdk.lib.mailbox import Mailbox


# --------------------------------
# Misc Fixtures utilities
# --------------------------------


@pytest.fixture(scope="session")
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


@pytest.fixture
def mock_responses():
    with responses.RequestsMock() as rsps:
        yield rsps


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
def filesystem_isolate(tmp_path):
    # Click>=8 implements temp_dir argument which depends on python>=3.7
    kwargs = dict(temp_dir=tmp_path) if sys.version_info >= (3, 7) else {}
    with CliRunner().isolated_filesystem(**kwargs):
        yield


# todo: this fixture should probably be autouse=True
@pytest.fixture(scope="function", autouse=False)
def local_settings(filesystem_isolate):
    """Place global settings in an isolated dir"""
    config_path = os.path.join(os.getcwd(), ".config", "wandb", "settings")
    filesystem.mkdir_exists_ok(os.path.join(".config", "wandb"))

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
        filesystem.mkdir_exists_ok("wandb")
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
                "run_id": runid.generate_id(),
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
