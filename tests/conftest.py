import pytest
import time
import datetime
import requests
import os
from contextlib import contextmanager
from tests import utils
# from multiprocessing import Process
import subprocess
import click
from click.testing import CliRunner
import webbrowser
import wandb
import git
import psutil
import atexit
from wandb.lib.globals import unset_globals
from wandb.internal.git_repo import GitRepo
from six.moves import urllib
try:
    import nbformat
except ImportError:  # TODO: no fancy notebook fun in python2
    pass

try:
    from unittest.mock import MagicMock
except ImportError:  # TODO: this is only for python2
    from mock import MagicMock

DUMMY_API_KEY = '1824812581259009ca9981580f8f8a9012409eee'
server = None


def test_cleanup(*args, **kwargs):
    global server
    server.terminate()
    print("Open files during tests: ")
    proc = psutil.Process()
    print(proc.open_files())


def start_mock_server():
    """We start a server on boot for use by tests"""
    global server
    port = utils.free_port()
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root, "tests", "utils", "mock_server.py")
    command = ["python", path]
    env = os.environ
    env["PORT"] = str(port)
    env["PYTHONPATH"] = root
    server = subprocess.Popen(command, env=env)
    server._port = port
    server.base_url = "http://localhost:%i" % server._port
    for i in range(5):
        try:
            res = requests.get("%s/storage" % server.base_url, timeout=1)
            if res.status_code == 200:
                break
            print("Attempting to connect but got: %s", res)
        except requests.exceptions.RequestException:
            print("timed out")
    return server


atexit.register(test_cleanup)
start_mock_server()


@pytest.fixture
def git_repo(runner):
    with runner.isolated_filesystem():
        r = git.Repo.init(".")
        os.mkdir("wandb")
        # Because the forked process doesn't use my monkey patch above
        with open("wandb/settings", "w") as f:
            f.write("[default]\nproject: test")
        open("README", "wb").close()
        r.index.add(["README"])
        r.index.commit("Initial commit")
        yield GitRepo(lazy=False)


@pytest.fixture
def test_settings():
    """ Settings object for tests"""
    settings = wandb.Settings(_start_time=time.time(),
                              run_id=wandb.util.generate_id(),
                              _start_datetime=datetime.datetime.now())
    settings.files_dir = settings._path_convert(settings.files_dir_spec)
    return settings


@pytest.fixture
def mocked_run(runner, test_settings):
    """ A managed run object for tests with a mock backend """
    with runner.isolated_filesystem():
        run = wandb.wandb_sdk.wandb_run.RunManaged(settings=test_settings)
        run._set_backend(MagicMock())
        yield run


@pytest.fixture
def runner(monkeypatch, mocker):
    # whaaaaat = util.vendor_import("whaaaaat")
    # monkeypatch.setattr('wandb.cli.api', InternalApi(
    #    default_settings={'project': 'test', 'git_tag': True}, load_settings=False))
    monkeypatch.setattr(click, 'launch', lambda x: 1)
    # monkeypatch.setattr(whaaaaat, 'prompt', lambda x: {
    #                    'project_name': 'test_model', 'files': ['weights.h5'],
    #                    'attach': False, 'team_name': 'Manual Entry'})
    monkeypatch.setattr(webbrowser, 'open_new_tab', lambda x: True)
    mocker.patch("wandb.lib.apikey.input", lambda x: 1)
    mocker.patch("wandb.lib.apikey.getpass.getpass", lambda x: DUMMY_API_KEY)
    return CliRunner()


@pytest.fixture(autouse=True)
def local_netrc(monkeypatch):
    """Never use our real credentials, put them in an isolated dir"""
    with CliRunner().isolated_filesystem():
        # TODO: this seems overkill...
        origexpand = os.path.expanduser

        def expand(path):
            return os.path.realpath("netrc") if "netrc" in path else origexpand(path)
        monkeypatch.setattr(os.path, "expanduser", expand)
        yield


@pytest.fixture
def mock_server():
    return utils.mock_server()


@pytest.fixture
def live_mock_server(request):
    global server
    name = urllib.parse.quote(request.node.name)
    # We set the username so the mock backend can namespace state
    os.environ["WANDB_USERNAME"] = name
    yield server
    del os.environ["WANDB_USERNAME"]


@pytest.fixture
def notebook(live_mock_server):
    """This launches a live server, configures a notebook to use it, and enables
    devs to execute arbitrary cells.  See tests/test_notebooks.py

    TODO: we should launch a single server on boot and namespace requests by host"""
    @contextmanager
    def notebook_loader(nb_path, kernel_name="wandb_python", **kwargs):
        with open(utils.notebook_path("setup.ipynb")) as f:
            setupnb = nbformat.read(f, as_version=4)
            setupcell = setupnb['cells'][0]
            # Ensure the notebooks talks to our mock server
            new_source = setupcell['source'].replace("__WANDB_BASE_URL__",
                                                     live_mock_server.base_url)
            setupcell['source'] = new_source

        with open(utils.notebook_path(nb_path)) as f:
            nb = nbformat.read(f, as_version=4)
        nb['cells'].insert(0, setupcell)

        client = utils.WandbNotebookClient(nb)
        with client.setup_kernel(**kwargs):
            # Run setup commands for mocks
            client.execute_cell(0, store_history=False)
            yield client
    notebook_loader.base_url = live_mock_server.base_url

    return notebook_loader


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
    marker = request.node.get_closest_marker('wandb_args')
    args = default_wandb_args()
    if marker:
        args.update(marker.kwargs)
    try:
        mocks_from_args(mocker, args, mock_server)
        for k, v in args["env"].items():
            os.environ[k] = v
        #  TODO: likely not the right thing to do, we shouldn't be setting this
        wandb._IS_INTERNAL_PROCESS = False
        #  We want to run setup every time in tests
        wandb.wandb_sdk.wandb_setup._WandbSetup._instance = None
        mocker.patch('wandb.wandb_sdk.wandb_init.Backend', utils.BackendMock)
        run = wandb.init(settings=wandb.Settings(console="off", mode="offline"),
                         **args["wandb_init"])
        yield run
        wandb.join()
    finally:
        unset_globals()
        for k, v in args["env"].items():
            del os.environ[k]
