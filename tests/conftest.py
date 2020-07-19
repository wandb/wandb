import pytest
import time
import datetime
import os
import requests
from tests import utils
from multiprocessing import Process
import click
from click.testing import CliRunner
import webbrowser
import wandb
import git
from wandb.internal.git_repo import GitRepo

try:
    from unittest.mock import MagicMock
except ImportError:  # TODO: this is only for python2
    from mock import MagicMock

DUMMY_API_KEY = '1824812581259009ca9981580f8f8a9012409eee'


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
    from tests.mock_server import create_app
    if request.node.get_closest_marker('port'):
        port = request.node.get_closest_marker('port').args[0]
    else:
        port = 8765
    app = create_app(utils.default_ctx())
    server = Process(target=app.run, kwargs={"port": port, "debug": True,
                                             "use_reloader": False})
    server.start()
    for i in range(5):
        try:
            time.sleep(1)
            res = requests.get("http://localhost:%s/storage" % port, timeout=1)
            if res.status_code == 200:
                break
            print("Attempting to connect but got: %s", res)
        except requests.exceptions.RequestException:
            print("timed out")
    yield server
    server.terminate()
    server.join()
