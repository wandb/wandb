import requests_mock
import os
from click.testing import CliRunner
import pytest
from wandb.history import History
from tests.api_mocks import *
import wandb
from wandb import wandb_run
from wandb.apis import InternalApi
import six
import json
import sys
import threading
import logging
from multiprocessing import Process
from vcr.request import Request
from wandb import wandb_socket
from wandb import env
from wandb import util
from wandb.wandb_run import Run
from tests import utils
from tests.mock_server import create_app


def pytest_runtest_setup(item):
    # This is used to find tests that are leaking outside of tmp directories
    os.environ["WANDB_DESCRIPTION"] = item.parent.name + "#" + item.name


def request_repr(self):
    try:
        body = json.loads(self.body)
        query = body.get("query") or "no_query"
        render = query.split("(")[0].split("\n")[0] + " - vars: " + str(body.get("variables", {}).get("files", {}))
    except (ValueError, TypeError):
        render = "BINARY"
    return "({}) {} - {}".format(self.method, self.uri, render)


Request.__repr__ = request_repr
# To enable VCR logging uncomment below
#logging.basicConfig() # you need to initialize logging, otherwise you will not see anything from vcrpy
#vcr_log = logging.getLogger("vcr")
#vcr_log.setLevel(logging.INFO)


@pytest.fixture(scope='module')
def vcr_config():
    def replace_body(request):
        if "storage.googleapis.com" in request.uri:
            request.body = "BINARY DATA"
        elif "/file_stream" in request.uri:
            request.body = json.dumps({"files": list(json.loads(request.body).get("files", {}.keys()))})
        return request

    def replace_response_body(response, *args):
        """Remove gzip response from pypi"""
        if response["headers"].get("Access-Control-Expose-Headers") == ['X-PyPI-Last-Serial']:
            if response["headers"].get("Content-Encoding"):
                del response["headers"]["Content-Encoding"]
            response["body"]["string"] = '{"info":{"version": "%s"}' % wandb.__version__
        return response

    return {
        # Replace the Authorization request header with "DUMMY" in cassettes
        "filter_headers": [('authorization', 'DUMMY')],
        "match_on": ['method', 'uri', 'query', 'graphql'],
        "before_record": replace_body,
        "before_record_response": replace_response_body,
    }


@pytest.fixture(scope='module')
def vcr(vcr):
    def vcr_graphql_matcher(r1, r2):
        if "/graphql" in r1.uri and "/graphql" in r2.uri:
            body1 = json.loads(r1.body.decode("utf-8"))
            body2 = json.loads(r2.body.decode("utf-8"))
            return body1["query"].strip() == body2["query"].strip()
        elif "/file_stream" in r1.uri and "/file_stream" in r2.uri:
            body1 = json.loads(r1.body.decode("utf-8"))
            body2 = json.loads(r2.body.decode("utf-8"))
            return body1["files"] == body2["files"]
    vcr.register_matcher('graphql', vcr_graphql_matcher)
    return vcr


@pytest.fixture
def local_netrc(monkeypatch):
    # TODO: this seems overkill...
    origexpand = os.path.expanduser

    def expand(path):
        return os.path.realpath("netrc") if "netrc" in path else origexpand(path)
    monkeypatch.setattr(os.path, "expanduser", expand)


@pytest.fixture
def history():
    with CliRunner().isolated_filesystem():
        yield Run().history


@pytest.fixture
def wandb_init_run(request, tmpdir, request_mocker, upsert_run, query_run_resume_status,
                   upload_logs, monkeypatch, mocker, capsys, local_netrc):
    """Fixture that calls wandb.init(), yields a run (or an exception) that
    gets created, then cleans up afterward.  This is meant to test the logic
    in wandb.init, it should generally not spawn a run_manager.  If you need
    to test run_manager logic use that fixture.
    """
    # save the environment so we can restore it later. pytest
    # may actually do this itself. didn't check.
    orig_environ = dict(os.environ)
    orig_namespace = None
    run = None
    try:
        with CliRunner().isolated_filesystem():
            upsert_run(request_mocker)
            if request.node.get_closest_marker('jupyter'):
                query_run_resume_status(request_mocker)

                def fake_ipython():
                    class Jupyter(object):
                        __module__ = "jupyter"

                        def __init__(self):
                            class Hook(object):
                                def register(self, what, where):
                                    pass
                            self.events = Hook()

                        def register_magics(self, magic):
                            pass
                    return Jupyter()
                wandb.get_ipython = fake_ipython
            # no i/o wrapping - it breaks pytest
            os.environ['WANDB_MODE'] = 'clirun'

            if request.node.get_closest_marker('headless'):
                mocker.patch('subprocess.Popen')
            else:
                def mock_headless(run, cloud=True):
                    print("_init_headless called with cloud=%s" % cloud)
                mocker.patch('wandb._init_headless', mock_headless)

            if not request.node.get_closest_marker('unconfigured'):
                os.environ['WANDB_API_KEY'] = 'test'
                os.environ['WANDB_ENTITY'] = 'test'
                os.environ['WANDB_PROJECT'] = 'unit-test-project'
            else:
                # when unconfigured we enable run mode to test missing creds
                os.environ['WANDB_MODE'] = 'run'
                monkeypatch.setattr('wandb.apis.InternalApi.api_key', None)
                monkeypatch.setattr(
                    'getpass.getpass', lambda x: "0123456789012345678901234567890123456789")
                assert InternalApi().api_key == None
            os.environ['WANDB_RUN_DIR'] = str(tmpdir)
            if request.node.get_closest_marker('silent'):
                os.environ['WANDB_SILENT'] = "true"

            assert wandb.run is None
            orig_namespace = vars(wandb)
            # Mock out run_manager, we add it to run to access state in tests
            orig_rm = wandb.run_manager.RunManager
            mock = mocker.patch('wandb.run_manager.RunManager')

            def fake_init(run, port=None, output=None):
                print("Initialized fake run manager")
                rm = fake_run_manager(mocker, run, rm_class=orig_rm)
                rm._block_file_observer()
                run.run_manager = rm
                return rm
            mock.side_effect = fake_init

            if request.node.get_closest_marker('args'):
                kwargs = request.node.get_closest_marker('args').kwargs
                # Unfortunate to enable the test to work
                if kwargs.get("dir"):
                    del os.environ['WANDB_RUN_DIR']
                if kwargs.get("tensorboard"):
                    # The test uses tensorboardX so we need to be sure it's imported
                    # we use get_module because tensorboardX isn't available in py2
                    wandb.util.get_module("tensorboardX")
                if kwargs.get("error"):
                    err = kwargs["error"]
                    del kwargs['error']

                    if err == "io":
                        @classmethod
                        def error(cls):
                            raise IOError
                        monkeypatch.setattr(
                            'wandb.wandb_run.Run.from_environment_or_defaults', error)
                    elif err == "socket":
                        class Error(object):
                            @property
                            def port(self):
                                return 123

                            def listen(self, secs):
                                return False, None
                        monkeypatch.setattr("wandb.wandb_socket.Server", Error)
                if kwargs.get('k8s') is not None:
                    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
                    crt_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
                    orig_exist = os.path.exists

                    def exists(path):
                        return True if path in token_path else orig_exist(path)

                    def magic(path, *args, **kwargs):
                        if path == token_path:
                            return six.StringIO('token')
                    mocker.patch('wandb.util.open', magic, create=True)
                    mocker.patch('wandb.util.os.path.exists', exists)
                    os.environ["KUBERNETES_SERVICE_HOST"] = "k8s"
                    os.environ["KUBERNETES_PORT_443_TCP_PORT"] = "123"
                    os.environ["HOSTNAME"] = "test"
                    if kwargs["k8s"]:
                        request_mocker.register_uri("GET", "https://k8s:123/api/v1/namespaces/default/pods/test",
                                                    content=b'{"status":{"containerStatuses":[{"imageID":"docker-pullable://test@sha256:1234"}]}}')
                    else:
                        request_mocker.register_uri("GET", "https://k8s:123/api/v1/namespaces/default/pods/test",
                                                    content=b'{}', status_code=500)
                    del kwargs["k8s"]
                if kwargs.get('sagemaker'):
                    del kwargs['sagemaker']
                    config_path = "/opt/ml/input/config/hyperparameters.json"
                    resource_path = "/opt/ml/input/config/resourceconfig.json"
                    secrets_path = "secrets.env"
                    os.environ['TRAINING_JOB_NAME'] = 'sage'
                    os.environ['CURRENT_HOST'] = 'maker'

                    orig_exist = os.path.exists

                    def exists(path):
                        return True if path in (config_path, secrets_path) else orig_exist(path)
                    mocker.patch('wandb.os.path.exists', exists)

                    def magic(path, *args, **kwargs):
                        if path == config_path:
                            return six.StringIO('{"fuckin": "A"}')
                        elif path == resource_path:
                            return six.StringIO('{"hosts":["a", "b"]}')
                        elif path == secrets_path:
                            return six.StringIO('WANDB_TEST_SECRET=TRUE')
                        else:
                            return six.StringIO()

                    mocker.patch('wandb.open', magic, create=True)
                    mocker.patch('wandb.util.open', magic, create=True)
                elif kwargs.get("tf_config"):
                    os.environ['TF_CONFIG'] = json.dumps(kwargs['tf_config'])
                    del kwargs['tf_config']
                elif kwargs.get("env"):
                    for k, v in six.iteritems(kwargs["env"]):
                        os.environ[k] = v
                    del kwargs["env"]
            else:
                kwargs = {}

            if request.node.get_closest_marker('resume'):
                # env was leaking when running the whole suite...
                if os.getenv(env.RUN_ID):
                    del os.environ[env.RUN_ID]
                query_run_resume_status(request_mocker)
                os.mkdir(wandb.wandb_dir())
                with open(os.path.join(wandb.wandb_dir(), wandb_run.RESUME_FNAME), "w") as f:
                    f.write(json.dumps({"run_id": "test"}))
            try:
                print("Initializing with", kwargs)
                run = wandb.init(**kwargs)
                if request.node.get_closest_marker('resume') or request.node.get_closest_marker('mocked_run_manager'):
                    # Reset history
                    run._history = None
                    rm = wandb.run_manager.RunManager(run)
                    rm.init_run(os.environ)
                if request.node.get_closest_marker('mock_socket'):
                    run.socket = mocker.MagicMock()
                assert run is wandb.run
                assert run.config is wandb.config
            except wandb.LaunchError as e:
                print("!!! wandb LaunchError raised")
                run = e
            yield run
            if hasattr(run, "run_manager"):
                print("Shutting down run manager")
                run.run_manager.test_shutdown()
    finally:
        # restore the original environment
        os.environ.clear()
        os.environ.update(orig_environ)
        wandb.uninit()
        wandb.get_ipython = lambda: None
        assert vars(wandb) == orig_namespace


def fake_run_manager(mocker, run=None, rm_class=wandb.run_manager.RunManager):
    # NOTE: This will create a run directory so make sure it's called in an isolated file system
    # We have an optional rm_class object because we mock it above so we need it before it's mocked
    api = InternalApi(load_settings=False)
    api.set_setting('project', 'testing')
    
    if wandb.run is None:
        wandb.run = run or Run()
    wandb.run._api = api
    wandb.run._mkdir()
    wandb.run.socket = wandb_socket.Server()
    api.set_current_run_id(wandb.run.id)
    mocker.patch('wandb.apis.internal.FileStreamApi')
    api._file_stream_api = mocker.MagicMock()
    run_manager = rm_class(wandb.run, port=wandb.run.socket.port)

    class FakeProc(object):
        def poll(self):
            return None

        def exit(self, code=0):
            return None
    run_manager.proc = FakeProc()
    run_manager._meta = mocker.MagicMock()
    run_manager._stdout_tee = mocker.MagicMock()
    run_manager._stderr_tee = mocker.MagicMock()
    run_manager._output_log = mocker.MagicMock()
    run_manager._stdout_stream = mocker.MagicMock()
    run_manager._stderr_stream = mocker.MagicMock()
    run_manager.mirror_stdout_stderr = mocker.MagicMock()
    run_manager.unmirror_stdout_stderr = mocker.MagicMock()
    socket_thread = threading.Thread(
        target=wandb.run.socket.listen)
    socket_thread.start()
    run_manager._socket.ready()
    thread = threading.Thread(
        target=run_manager._sync_etc)
    thread.daemon = True
    thread.start()

    def test_shutdown():
        if wandb.run and wandb.run.socket:
            wandb.run.socket.done()
            # TODO: is this needed?
            socket_thread.join()
            thread.join()
    run_manager.test_shutdown = test_shutdown
    run_manager._unblock_file_observer()
    run_manager._file_pusher._push_function = mocker.MagicMock()
    return run_manager


@pytest.fixture
def run_manager(mocker, request_mocker, upsert_run, query_viewer):
    """This fixture emulates the run_manager headless mode in a single process
    Just call run_manager.test_shutdown() to join the threads
    """
    with CliRunner().isolated_filesystem():
        query_viewer(request_mocker)
        upsert_run(request_mocker)
        run_manager = fake_run_manager(mocker)
        yield run_manager
        wandb.uninit()


# "Error: 'Session' object has no attribute 'request'""
# @pytest.fixture(autouse=True)
# def no_requests(monkeypatch):
#    monkeypatch.delattr("requests.sessions.Session.request")

@pytest.fixture
def request_mocker(request):
    """
    :param request: pytest request object for cleaning up.
    :return: Returns instance of requests mocker used to mock HTTP calls.
    """
    m = requests_mock.Mocker()
    m.start()
    request.addfinalizer(m.stop)
    return m


@pytest.fixture
def mock_server(mocker, request_mocker):
    app = create_app()
    mock = utils.RequestsMock(app.test_client(), {})
    mocker.patch("gql.transport.requests.requests", mock)
    mocker.patch("wandb.apis.file_stream.requests", mock)
    mocker.patch("wandb.apis.internal.requests", mock)
    return mock


@pytest.fixture
def live_mock_server(request):
    if request.node.get_closest_marker('port'):
        port = request.node.get_closest_marker('port').args[0]
    else:
        port = 8765
    app = create_app()
    server = Process(target=app.run, kwargs={"port": port, "debug": True, "use_reloader": False})
    server.start()
    yield server
    server.terminate()
    server.join()
