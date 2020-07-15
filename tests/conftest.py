import pytest
import time
import os
import sys
import requests
from tests import utils
from multiprocessing import Process
# from wandb import util
import click
from click.testing import CliRunner
import webbrowser

DUMMY_API_KEY = '1824812581259009ca9981580f8f8a9012409eee'


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
    if sys.version_info < (3, 5):
        sdk = "sdk_py27"
    else:
        sdk = "sdk"
    mocker.patch('wandb.%s.wandb_login.prompt' % sdk,
                 lambda *args, **kwargs: DUMMY_API_KEY)
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


def default_ctx():
    return {
        "fail_count": 0,
        "page_count": 0,
        "page_times": 2,
        "files": {},
    }


@pytest.fixture
def mock_server(mocker):
    from tests.mock_server import create_app
    ctx = default_ctx()
    app = create_app(ctx)
    mock = utils.RequestsMock(app, ctx)
    if sys.version_info < (3, 5):
        sdk = "sdk_py27"
    else:
        sdk = "sdk"
    mocker.patch("gql.transport.requests.requests", mock)
    mocker.patch("wandb.internal.file_stream.requests", mock)
    mocker.patch("wandb.internal.internal_api.requests", mock)
    mocker.patch("wandb.internal.update.requests", mock)
    mocker.patch("wandb.apis.internal_runqueue.requests", mock)
    mocker.patch("wandb.apis.public.requests", mock)
    mocker.patch("wandb.util.requests", mock)
    mocker.patch("wandb.%s.wandb_artifacts.requests" % sdk, mock)
    return mock


@pytest.fixture
def live_mock_server(request):
    from tests.mock_server import create_app
    if request.node.get_closest_marker('port'):
        port = request.node.get_closest_marker('port').args[0]
    else:
        port = 8765
    app = create_app(default_ctx())
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
