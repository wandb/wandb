import atexit
import logging
import os
import platform
import queue
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib
import webbrowser
from contextlib import contextmanager
from typing import Optional
from unittest import mock
from unittest.mock import MagicMock

import click
import git
import nbformat
import psutil
import pytest
import requests
import wandb
from click.testing import CliRunner
from wandb import Api, wandb_sdk
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.handler import HandleManager
from wandb.sdk.internal.internal_api import Api as InternalApi
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.lib.git import GitRepo
from wandb.sdk.lib.module import unset_globals
from wandb.util import mkdir_exists_ok

from . import utils

DUMMY_API_KEY = "1824812581259009ca9981580f8f8a9012409eee"


class ServerMap:
    def __init__(self):
        self._map = {}

    def items(self):
        return self._map.items()

    def __getitem__(self, worker_id):
        if self._map.get(worker_id) is None:
            self._map[worker_id] = start_mock_server(worker_id)
        return self._map[worker_id]


servers = ServerMap()


def test_cleanup(*args, **kwargs):
    print("Shutting down mock servers")
    for wid, server in servers.items():
        print(f"Shutting down {wid}")
        server.terminate()
    print("Open files during tests: ")
    proc = psutil.Process()
    print(proc.open_files())


def wait_for_port_file(port_file):
    port = 0
    start_time = time.time()
    while not port:
        try:
            port = int(open(port_file).read().strip())
            if port:
                break
        except Exception as e:
            print(f"Problem parsing port file: {e}")
        now = time.time()
        if now > start_time + 30:
            raise Exception(f"Could not start server {now} {start_time}")
        time.sleep(0.5)
    return port


def start_mock_server(worker_id):
    """We start a flask server process for each pytest-xdist worker_id"""
    this_folder = os.path.dirname(__file__)
    path = os.path.join(this_folder, "utils", "mock_server.py")
    command = [sys.executable, "-u", path]
    env = os.environ
    env["PORT"] = "0"  # Let the server find its own port
    env["PYTHONPATH"] = os.path.abspath(os.path.join(this_folder, os.pardir))
    logfname = os.path.join(this_folder, "logs", f"live_mock_server-{worker_id}.log")
    pid = os.getpid()
    rand = random.randint(0, 2**32)
    port_file = os.path.join(
        this_folder, "logs", f"live_mock_server-{worker_id}-{pid}-{rand}.port"
    )
    env["PORT_FILE"] = port_file
    logfile = open(logfname, "w")
    server = subprocess.Popen(
        command,
        stdout=logfile,
        env=env,
        stderr=subprocess.STDOUT,
        bufsize=1,
        close_fds=True,
    )

    port = wait_for_port_file(port_file)
    server._port = port
    server.base_url = f"http://localhost:{server._port}"

    def get_ctx():
        return requests.get(server.base_url + "/ctx").json()

    def set_ctx(payload):
        return requests.put(server.base_url + "/ctx", json=payload).json()

    def reset_ctx():
        return requests.delete(server.base_url + "/ctx").json()

    server.get_ctx = get_ctx
    server.set_ctx = set_ctx
    server.reset_ctx = reset_ctx

    started = False
    for i in range(10):
        try:
            res = requests.get("%s/ctx" % server.base_url, timeout=5)
            if res.status_code == 200:
                started = True
                break
            print(f"Attempting to connect but got: {res}")
        except requests.exceptions.RequestException:
            print(
                "Timed out waiting for server to start...", server.base_url, time.time()
            )
            if server.poll() is None:
                time.sleep(1)
            else:
                raise ValueError("Server failed to start.")
    if started:
        print(f"Mock server listing on {server._port} see {logfname}")
    else:
        server.terminate()
        print(f"Server failed to launch, see {logfname}")
        try:
            print("=" * 40)
            with open(logfname) as f:
                for logline in f.readlines():
                    print(logline.strip())
            print("=" * 40)
        except Exception as e:
            print("EXCEPTION:", e)
        raise ValueError("Failed to start server!  Exit code %s" % server.returncode)
    return server


atexit.register(test_cleanup)


@pytest.fixture
def test_name(request):
    # change "test[1]" to "test__1__"
    name = urllib.parse.quote(request.node.name.replace("[", "__").replace("]", "__"))
    return name


@pytest.fixture
def test_dir(test_name):
    orig_dir = os.getcwd()
    root = os.path.abspath(os.path.dirname(__file__))
    test_dir = os.path.join(root, "logs", test_name)
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    mkdir_exists_ok(test_dir)
    os.chdir(test_dir)
    yield test_dir
    os.chdir(orig_dir)


@pytest.fixture
def disable_git_save():
    with mock.patch.dict("os.environ", WANDB_DISABLE_GIT="true"):
        yield


@pytest.fixture
def git_repo(runner):
    with runner.isolated_filesystem():
        with git.Repo.init(".") as repo:
            mkdir_exists_ok("wandb")
            # Because the forked process doesn't use my monkey patch above
            with open(os.path.join("wandb", "settings"), "w") as f:
                f.write("[default]\nproject: test")
            open("README", "wb").close()
            repo.index.add(["README"])
            repo.index.commit("Initial commit")
            yield GitRepo(lazy=False)


@pytest.fixture
def git_repo_fn(runner):
    def git_repo_fn_helper(
        path: str = ".",
        remote_name: str = "origin",
        remote_url: Optional[str] = "https://foo:bar@github.com/FooTest/Foo.git",
        commit_msg: Optional[str] = None,
    ):
        with git.Repo.init(path) as repo:
            mkdir_exists_ok("wandb")
            if remote_url is not None:
                repo.create_remote(remote_name, remote_url)
            if commit_msg is not None:
                repo.index.commit(commit_msg)
            return GitRepo(lazy=False)

    with runner.isolated_filesystem():
        yield git_repo_fn_helper


@pytest.fixture
def dummy_api_key():
    return DUMMY_API_KEY


@pytest.fixture
def reinit_internal_api():
    with mock.patch("wandb.api", InternalApi()):
        yield


@pytest.fixture
def test_settings(test_dir, mocker, live_mock_server):
    """Settings object for tests"""
    #  TODO: likely not the right thing to do, we shouldn't be setting this
    wandb._IS_INTERNAL_PROCESS = False
    wandb.wandb_sdk.wandb_run.EXIT_TIMEOUT = 15
    wandb.wandb_sdk.wandb_setup._WandbSetup.instance = None
    wandb_dir = os.path.join(test_dir, "wandb")
    mkdir_exists_ok(wandb_dir)
    settings = wandb.Settings(
        api_key=DUMMY_API_KEY,
        base_url=live_mock_server.base_url,
        console="off",
        host="test",
        project="test",
        root_dir=test_dir,
        run_id=wandb.util.generate_id(),
        save_code=False,
    )
    settings._set_run_start_time()
    yield settings
    # Just in case someone forgets to join in tests. ...well, please don't!
    if wandb.run is not None:
        wandb.run.finish()


@pytest.fixture
def mocked_run(runner, test_settings):
    """A managed run object for tests with a mock backend"""
    run = wandb.wandb_sdk.wandb_run.Run(settings=test_settings)
    run._set_backend(MagicMock())
    yield run


@pytest.fixture
def runner(monkeypatch, mocker):
    # monkeypatch.setattr('wandb.cli.api', InternalApi(
    #    default_settings={'project': 'test', 'git_tag': True}, load_settings=False))
    monkeypatch.setattr(
        wandb.util, "prompt_choices", lambda x, input_timeout=None, jupyter=False: x[0]
    )
    monkeypatch.setattr(
        wandb.wandb_lib.apikey,
        "prompt_choices",
        lambda x, input_timeout=None, jupyter=False: x[0],
    )
    monkeypatch.setattr(click, "launch", lambda x: 1)
    monkeypatch.setattr(webbrowser, "open_new_tab", lambda x: True)
    mocker.patch("wandb.wandb_lib.apikey.isatty", lambda stream: True)
    mocker.patch("wandb.wandb_lib.apikey.input", lambda x: 1)
    mocker.patch("wandb.wandb_lib.apikey.getpass", lambda x: DUMMY_API_KEY)
    return CliRunner()


@pytest.fixture(autouse=True)
def reset_setup():
    def teardown():
        wandb.wandb_sdk.wandb_setup._WandbSetup._instance = None

    getattr(wandb, "teardown", teardown)()
    yield
    getattr(wandb, "teardown", lambda: None)()


@pytest.fixture(autouse=True)
def local_netrc(monkeypatch):
    """Never use our real credentials, put them in their own isolated dir"""
    with CliRunner().isolated_filesystem():
        # TODO: this seems overkill...
        origexpand = os.path.expanduser
        # Touch that netrc
        open(".netrc", "wb").close()

        def expand(path):
            if "netrc" in path:
                try:
                    ret = os.path.realpath("netrc")
                except OSError:
                    ret = origexpand(path)
            else:
                ret = origexpand(path)
            return ret

        monkeypatch.setattr(os.path, "expanduser", expand)
        yield


@pytest.fixture(autouse=True)
def local_settings(mocker):
    """Place global settings in an isolated dir"""
    with CliRunner().isolated_filesystem():
        cfg_path = os.path.join(os.getcwd(), ".config", "wandb", "settings")
        mkdir_exists_ok(os.path.join(".config", "wandb"))
        mocker.patch("wandb.old.settings.Settings._global_path", return_value=cfg_path)
        yield


@pytest.fixture
def mock_server(mocker):
    return utils.mock_server(mocker)


# We create one live_mock_server per pytest-xdist worker
@pytest.fixture
def live_mock_server(request, worker_id):
    global servers
    server = servers[worker_id]
    name = urllib.parse.quote(request.node.name)
    # We set the username so the mock backend can namespace state
    with mock.patch.dict(
        os.environ,
        {
            "WANDB_USERNAME": name,
            "WANDB_BASE_URL": server.base_url,
            "WANDB_ERROR_REPORTING": "false",
            "WANDB_API_KEY": DUMMY_API_KEY,
        },
    ):
        # clear mock server ctx
        server.reset_ctx()
        yield server


@pytest.fixture
def notebook(live_mock_server, test_dir):
    """This launches a live server, configures a notebook to use it, and enables
    devs to execute arbitrary cells.  See tests/test_notebooks.py
    """

    @contextmanager
    def notebook_loader(nb_path, kernel_name="wandb_python", save_code=True, **kwargs):
        with open(utils.notebook_path("setup.ipynb")) as f:
            setupnb = nbformat.read(f, as_version=4)
            setupcell = setupnb["cells"][0]
            # Ensure the notebooks talks to our mock server
            new_source = setupcell["source"].replace(
                "__WANDB_BASE_URL__",
                live_mock_server.base_url,
            )
            if save_code:
                new_source = new_source.replace("__WANDB_NOTEBOOK_NAME__", nb_path)
            else:
                new_source = new_source.replace("__WANDB_NOTEBOOK_NAME__", "")
            setupcell["source"] = new_source

        nb_path = utils.notebook_path(nb_path)
        shutil.copy(nb_path, os.path.join(os.getcwd(), os.path.basename(nb_path)))
        with open(nb_path) as f:
            nb = nbformat.read(f, as_version=4)
        nb["cells"].insert(0, setupcell)

        try:
            client = utils.WandbNotebookClient(nb, kernel_name=kernel_name)
            with client.setup_kernel(**kwargs):
                # Run setup commands for mocks
                client.execute_cells(-1, store_history=False)
                yield client
        finally:
            with open(os.path.join(os.getcwd(), "notebook.log"), "w") as f:
                f.write(client.all_output_text())
            wandb.termlog("Find debug logs at: %s" % os.getcwd())
            wandb.termlog(client.all_output_text())

    notebook_loader.base_url = live_mock_server.base_url

    return notebook_loader


@pytest.fixture
def mocked_module(monkeypatch):
    """This allows us to mock modules loaded via wandb.util.get_module"""

    def mock_get_module(module):
        orig_get_module = wandb.util.get_module
        mocked_module = MagicMock()

        def get_module(mod):
            if mod == module:
                return mocked_module
            else:
                return orig_get_module(mod)

        monkeypatch.setattr(wandb.util, "get_module", get_module)
        return mocked_module

    return mock_get_module


@pytest.fixture
def mocked_ipython(mocker):
    mocker.patch("wandb.sdk.lib.ipython._get_python_type", lambda: "jupyter")
    mocker.patch("wandb.sdk.wandb_settings._get_python_type", lambda: "jupyter")
    html_mock = mocker.MagicMock()
    mocker.patch("wandb.sdk.lib.ipython.display_html", html_mock)
    ipython = MagicMock()
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


def default_wandb_args():
    """This allows us to parameterize the wandb_init_run fixture
    The most general arg is "env", you can call:

    @pytest.mark.wandb_args(env={"WANDB_API_KEY": "XXX"})

    To set env vars and have them unset when the test completes.
    """
    return {
        "error": None,
        "k8s": None,
        "sagemaker": False,
        "tensorboard": False,
        "resume": False,
        "env": {},
        "wandb_init": {},
    }


def mocks_from_args(mocker, args, mock_server):
    if args["k8s"] is not None:
        mock_server.ctx["k8s"] = args["k8s"]
        args["env"].update(utils.mock_k8s(mocker))
    if args["sagemaker"]:
        args["env"].update(utils.mock_sagemaker(mocker))


@pytest.fixture
def wandb_init_run(request, runner, mocker, mock_server):
    marker = request.node.get_closest_marker("wandb_args")
    args = default_wandb_args()
    if marker:
        args.update(marker.kwargs)
    try:
        mocks_from_args(mocker, args, mock_server)
        with mock.patch.dict(os.environ, {k: v for k, v in args["env"].items()}):
            #  TODO: likely not the right thing to do, we shouldn't be setting this
            wandb._IS_INTERNAL_PROCESS = False
            run = wandb.init(
                settings=dict(console="off", mode="offline", _except_exit=False),
                **args["wandb_init"],
            )
            yield run
            run.finish()
    finally:
        unset_globals()


@pytest.fixture
def wandb_init(request, runner, mocker, mock_server):
    def init(*args, **kwargs):
        try:
            mocks_from_args(mocker, default_wandb_args(), mock_server)
            #  TODO: likely not the right thing to do, we shouldn't be setting this
            wandb._IS_INTERNAL_PROCESS = False
            return wandb.init(
                settings=dict(console="off", mode="offline", _except_exit=False),
                *args,
                **kwargs,
            )
        finally:
            unset_globals()

    return init


@pytest.fixture()
def restore_version():
    save_current_version = wandb.__version__
    yield
    wandb.__version__ = save_current_version
    try:
        del wandb.__hack_pypi_latest_version__
    except AttributeError:
        pass


@pytest.fixture()
def parse_ctx():
    """Fixture providing class to parse context data."""

    def parse_ctx_fn(ctx, run_id=None):
        return utils.ParseCTX(ctx, run_id=run_id)

    yield parse_ctx_fn


@pytest.fixture()
def record_q():
    return queue.Queue()


@pytest.fixture()
def fake_interface(record_q):
    return InterfaceQueue(record_q=record_q)


@pytest.fixture
def fake_backend(fake_interface):
    class FakeBackend:
        def __init__(self):
            self.interface = fake_interface

    yield FakeBackend()


@pytest.fixture
def fake_run(fake_backend):
    def run_fn():
        s = wandb.Settings()
        run = wandb_sdk.wandb_run.Run(settings=s)
        run._set_backend(fake_backend)
        return run

    yield run_fn


@pytest.fixture
def records_util():
    def records_fn(q):
        ru = utils.RecordsUtil(q)
        return ru

    yield records_fn


@pytest.fixture
def user_test(fake_run, record_q, records_util):
    class UserTest:
        pass

    ut = UserTest()
    ut.get_run = fake_run
    ut.get_records = lambda: records_util(record_q)

    yield ut


# @pytest.hookimpl(tryfirst=True, hookwrapper=True)
# def pytest_runtest_makereport(item, call):
#     outcome = yield
#     rep = outcome.get_result()
#     if rep.when == "call" and rep.failed:
#         print("DEBUG PYTEST", rep, item, call, outcome)


@pytest.fixture
def log_debug(caplog):
    caplog.set_level(logging.DEBUG)
    yield
    # for rec in caplog.records:
    #     print("LOGGER", rec.message, file=sys.stderr)


# ----------------------
# internal test fixtures
# ----------------------


@pytest.fixture()
def internal_result_q():
    return queue.Queue()


@pytest.fixture()
def internal_sender_q():
    return queue.Queue()


@pytest.fixture()
def internal_writer_q():
    return queue.Queue()


@pytest.fixture()
def internal_process():
    # FIXME: return mocked process (needs is_alive())
    return MockProcess()


class MockProcess:
    def __init__(self):
        self._alive = True

    def is_alive(self):
        return self._alive


@pytest.fixture()
def _internal_sender(record_q, internal_result_q, internal_process):
    return InterfaceQueue(
        record_q=record_q,
        result_q=internal_result_q,
        process=internal_process,
    )


@pytest.fixture()
def internal_sm(
    runner,
    internal_sender_q,
    internal_result_q,
    test_settings,
    mock_server,
    _internal_sender,
):
    with runner.isolated_filesystem():
        test_settings.update(
            root_dir=os.getcwd(), source=wandb.sdk.wandb_settings.Source.INIT
        )
        sm = SendManager(
            settings=test_settings,
            record_q=internal_sender_q,
            result_q=internal_result_q,
            interface=_internal_sender,
        )
        yield sm


@pytest.fixture()
def stopped_event():
    stopped = threading.Event()
    yield stopped


@pytest.fixture()
def internal_hm(
    runner,
    record_q,
    internal_result_q,
    test_settings,
    mock_server,
    internal_sender_q,
    internal_writer_q,
    _internal_sender,
    stopped_event,
):
    with runner.isolated_filesystem():
        test_settings.update(
            root_dir=os.getcwd(), source=wandb.sdk.wandb_settings.Source.INIT
        )
        hm = HandleManager(
            settings=test_settings,
            record_q=record_q,
            result_q=internal_result_q,
            stopped=stopped_event,
            sender_q=internal_sender_q,
            writer_q=internal_writer_q,
            interface=_internal_sender,
        )
        yield hm


@pytest.fixture()
def internal_get_record():
    def _get_record(input_q, timeout=None):
        try:
            i = input_q.get(timeout=timeout)
        except queue.Empty:
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
            except Exception as e:
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
def start_handle_thread(record_q, internal_get_record, stopped_event):
    def start_handle(handle_manager):
        def target():
            while True:
                payload = internal_get_record(input_q=record_q, timeout=0.1)
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
    mocked_run,
    internal_hm,
    internal_sm,
    _internal_sender,
    start_handle_thread,
    start_send_thread,
    log_debug,
):
    def start_backend_func(initial_run=True, initial_start=False):
        ht = start_handle_thread(internal_hm)
        st = start_send_thread(internal_sm)
        if initial_run:
            run = _internal_sender.communicate_run(mocked_run)
            if initial_start:
                _internal_sender.communicate_run_start(run.run)
        return (ht, st)

    yield start_backend_func


@pytest.fixture()
def _stop_backend(
    mocked_run,
    internal_hm,
    internal_sm,
    _internal_sender,
    start_handle_thread,
    start_send_thread,
    collect_responses,
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
                    collect_responses.poll_exit_resp = poll_exit_resp
                    break
            time.sleep(1)
        _internal_sender.join()
        for t in threads:
            t.join()
        assert done, "backend didnt shutdown"

    yield stop_backend_func


@pytest.fixture()
def backend_interface(_start_backend, _stop_backend, _internal_sender):
    @contextmanager
    def backend_context(initial_run=True, initial_start=False):
        threads = _start_backend(initial_run=initial_run, initial_start=initial_start)
        try:
            yield _internal_sender
        finally:
            _stop_backend(threads=threads)

    return backend_context


@pytest.fixture
def publish_util(
    mocked_run,
    mock_server,
    backend_interface,
    parse_ctx,
):
    def fn(
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

        with backend_interface(initial_start=initial_start) as interface:
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
        ctx_util = parse_ctx(mock_server.ctx, run_id=mocked_run.id)
        return ctx_util

    yield fn


@pytest.fixture
def tbwatcher_util(mocked_run, mock_server, internal_hm, backend_interface, parse_ctx):
    def fn(write_function, logdir="./", save=True, root_dir="./"):

        with backend_interface() as interface:
            proto_run = pb.RunRecord()
            mocked_run._make_proto_run(proto_run)

            run_start = pb.RunStartRequest()
            run_start.run.CopyFrom(proto_run)

            request = pb.Request()
            request.run_start.CopyFrom(run_start)

            record = pb.Record()
            record.request.CopyFrom(request)
            internal_hm.handle_request_run_start(record)
            internal_hm._tb_watcher.add(logdir, save, root_dir)

            # need to sleep to give time for the tb_watcher delay
            time.sleep(15)
            write_function()

        ctx_util = parse_ctx(mock_server.ctx)
        return ctx_util

    yield fn


@pytest.fixture
def inject_requests(mock_server):
    """Fixture for injecting responses and errors to mock_server."""

    # TODO(jhr): make this compatible with live_mock_server
    return utils.InjectRequests(ctx=mock_server.ctx)


class Responses:
    pass


@pytest.fixture
def collect_responses():
    responses = Responses()
    yield responses


@pytest.fixture
def mock_tty(monkeypatch):
    class WriteThread(threading.Thread):
        def __init__(self, fname):
            threading.Thread.__init__(self)
            self._fname = fname
            self._q = queue.Queue()

        def run(self):
            with open(self._fname, "w") as fp:
                while True:
                    data = self._q.get()
                    if data == "_DONE_":
                        break
                    fp.write(data)
                    fp.flush()

        def add(self, input_str):
            self._q.put(input_str)

        def stop(self):
            self.add("_DONE_")

    with tempfile.TemporaryDirectory() as tmpdir:
        fds = dict()

        def setup_fn(input_str):
            fname = os.path.join(tmpdir, "file.txt")
            if platform.system() != "Windows":
                os.mkfifo(fname, 0o600)
                writer = WriteThread(fname)
                writer.start()
                writer.add(input_str)
                fds["writer"] = writer
                monkeypatch.setattr("termios.tcflush", lambda x, y: None)
            else:
                # windows doesn't support named pipes, just write it
                # TODO: emulate msvcrt to support input on windows
                with open(fname, "w") as fp:
                    fp.write(input_str)
            fds["stdin"] = open(fname)
            monkeypatch.setattr("sys.stdin", fds["stdin"])
            sys.stdin.isatty = lambda: True
            sys.stdout.isatty = lambda: True

        yield setup_fn

        writer = fds.get("writer")
        if writer:
            writer.stop()
            writer.join()
        stdin = fds.get("stdin")
        if stdin:
            stdin.close()

    del sys.stdin.isatty
    del sys.stdout.isatty


@pytest.fixture
def api(runner):
    return Api()
