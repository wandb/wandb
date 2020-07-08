import pytest
import os
import sys
import click
from click.testing import CliRunner
import git
import requests
import json
from wandb import util
from wandb.apis import InternalApi

import webbrowser
from wandb.git_repo import GitRepo
from distutils.version import LooseVersion

torch = util.get_module("torch")
if torch:
    if LooseVersion(torch.__version__) < LooseVersion("0.4"):
        pytorch_tensor = torch.Tensor
        OLD_PYTORCH = True
    else:
        # supports 0d tensors but is a module before 0.4
        pytorch_tensor = torch.tensor
        OLD_PYTORCH = False


@pytest.fixture
def runner(monkeypatch, mocker):
    whaaaaat = util.vendor_import("whaaaaat")
    monkeypatch.setattr('wandb.cli.api', InternalApi(
        default_settings={'project': 'test', 'git_tag': True}, load_settings=False))
    monkeypatch.setattr(click, 'launch', lambda x: 1)
    monkeypatch.setattr(whaaaaat, 'prompt', lambda x: {
                        'project_name': 'test_model', 'files': ['weights.h5'], 'attach': False,
                        'team_name': 'Manual Entry'})
    monkeypatch.setattr(webbrowser, 'open_new_tab', lambda x: True)
    return CliRunner()


@pytest.fixture
def git_repo():
    with CliRunner().isolated_filesystem():
        r = git.Repo.init(".")
        os.mkdir("wandb")
        # Because the forked process doesn't use my monkey patch above
        with open("wandb/settings", "w") as f:
            f.write("[default]\nproject: test")
        open("README", "wb").close()
        r.index.add(["README"])
        r.index.commit("Initial commit")
        yield GitRepo(lazy=False)


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
                    print('Diff at index: %s' % list(reversed(indices)))


def subdict(d, expected_dict):
    """Return a new dict with only the items from `d` whose keys occur in `expected_dict`.
    """
    return {k: v for k, v in d.items() if k in expected_dict}


class ResponseMock(object):
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        if self.response.status_code >= 400:
            raise requests.exceptions.HTTPError("Bad Request", response=self.response)

    @property
    def content(self):
        return self.response.data.decode('utf-8')

    def iter_content(self, chunk_size=1024):
        yield self.response.data

    def json(self):
        return json.loads(self.response.data.decode('utf-8'))


class RequestsMock(object):
    def __init__(self, app, ctx):
        self.app = app
        self.client = app.test_client()
        self.ctx = ctx

    def set_context(self, key, value):
        self.ctx[key] = value

    def Session(self):
        return self

    @property
    def RequestException(self):
        return requests.RequestException

    @property
    def HTTPError(self):
        return requests.HTTPError

    @property
    def headers(self):
        return {}

    @property
    def utils(self):
        return requests.utils

    @property
    def exceptions(self):
        return requests.exceptions

    @property
    def packages(self):
        return requests.packages

    @property
    def adapters(self):
        return requests.adapters

    def mount(self, *args):
        pass

    def _clean_kwargs(self, kwargs):
        if "auth" in kwargs:
            del kwargs["auth"]
        if "timeout" in kwargs:
            del kwargs["timeout"]
        if "cookies" in kwargs:
            del kwargs["cookies"]
        if "params" in kwargs:
            del kwargs["params"]
        if "stream" in kwargs:
            del kwargs["stream"]
        if "verify" in kwargs:
            del kwargs["verify"]
        if "allow_redirects" in kwargs:
            del kwargs["allow_redirects"]
        return kwargs

    def _store_request(self, url, body):
        key = url.split("/")[-1]
        self.ctx[key] = self.ctx.get(key, [])
        self.ctx[key].append(body)

    def post(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.post(url, **self._clean_kwargs(kwargs)))

    def put(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.put(url, **self._clean_kwargs(kwargs)))

    def get(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.get(url, **self._clean_kwargs(kwargs)))

    def request(self, method, url, **kwargs):
        if method.lower() == "get":
            self.get(url, **kwargs)
        elif method.lower() == "post":
            self.post(url, **kwargs)
        elif method.lower() == "put":
            self.put(url, **kwargs)
        else:
            raise requests.RequestException("Request method not implemented: %s" % method)