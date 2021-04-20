import os
import shutil
import six
import socket


def subdict(d, expected_dict):
    """Return a new dict with only the items from `d` whose keys occur in `expected_dict`.
    """
    return {k: v for k, v in d.items() if k in expected_dict}


def fixture_path(path):
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "fixtures", path
    )


def first_filestream(ctx):
    """In xdist tests sometimes rougue file_streams make it to the server,
    we grab the first request with `files`"""
    return next(m for m in ctx["file_stream"] if m.get("files"))


def fixture_open(path, mode="r"):
    """Returns an opened fixture file"""
    return open(fixture_path(path), mode)


def fixture_copy(path, dst=None):
    if os.path.isfile(fixture_path(path)):
        return shutil.copy(fixture_path(path), dst or path)
    else:
        return shutil.copytree(fixture_path(path), dst or path)


def notebook_path(path):
    """Returns the path to a notebook"""
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "notebooks", path)
    )


def free_port():
    sock = socket.socket()
    sock.bind(("", 0))

    _, port = sock.getsockname()
    return port


def assert_deep_lists_equal(a, b, indices=None):
    try:
        assert a == b
    except ValueError:
        assert len(a) == len(b)

        # pytest's list diffing breaks at 4d so we track them ourselves
        if indices is None:
            indices = []
            top = True
        else:
            top = False

        for i, (x, y) in enumerate(zip(a, b)):
            try:
                assert_deep_lists_equal(x, y, indices)
            except AssertionError:
                indices.append(i)
                raise
            finally:
                if top and indices:
                    print("Diff at index: %s" % list(reversed(indices)))


def mock_sagemaker(mocker):
    env = {}
    config_path = "/opt/ml/input/config/hyperparameters.json"
    resource_path = "/opt/ml/input/config/resourceconfig.json"
    secrets_path = "secrets.env"
    env["TRAINING_JOB_NAME"] = "sage"
    env["CURRENT_HOST"] = "maker"

    orig_exist = os.path.exists

    def exists(path):
        if path in (config_path, secrets_path, resource_path):
            return True
        else:
            return orig_exist(path)

    mocker.patch("wandb.util.os.path.exists", exists)

    def magic(path, *args, **kwargs):
        if path == config_path:
            return six.StringIO('{"fuckin": "A"}')
        elif path == resource_path:
            return six.StringIO('{"hosts":["a", "b"]}')
        elif path == secrets_path:
            return six.StringIO("WANDB_TEST_SECRET=TRUE")
        else:
            return six.StringIO()

    mocker.patch("builtins.open", magic, create=True)
    return env


def mock_k8s(mocker):
    env = {}
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    #  crt_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    orig_exist = os.path.exists

    def exists(path):
        return True if path in token_path else orig_exist(path)

    def magic(path, *args, **kwargs):
        if path == token_path:
            return six.StringIO("token")

    mocker.patch("wandb.util.open", magic, create=True)
    mocker.patch("wandb.util.os.path.exists", exists)
    env["KUBERNETES_SERVICE_HOST"] = "k8s"
    env["KUBERNETES_PORT_443_TCP_PORT"] = "123"
    env["HOSTNAME"] = "test"
    return env
