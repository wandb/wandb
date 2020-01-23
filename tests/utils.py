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

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.response.data.decode('utf-8'))


class RequestsMock(object):
    def __init__(self, client, requests):
        self.client = client
        self.requests = requests

    def Session(self):
        return self

    @property
    def RequestException(self):
        return requests.RequestException

    @property
    def headers(self):
        return {}

    @property
    def utils(self):
        return requests.utils

    @property
    def exceptions(self):
        return requests.exceptions

    def _clean_kwargs(self, kwargs):
        if "auth" in kwargs:
            del kwargs["auth"]
        if "timeout" in kwargs:
            del kwargs["timeout"]
        if "cookies" in kwargs:
            del kwargs["cookies"]
        return kwargs

    def _store_request(self, url, body):
        key = url.split("/")[-1]
        self.requests[key] = self.requests.get(key, [])
        self.requests[key].append(body)

    def post(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.post(url, **self._clean_kwargs(kwargs)))

    def put(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.put(url, **self._clean_kwargs(kwargs)))

    def get(self, url, **kwargs):
        self._store_request(url, kwargs.get("json"))
        return ResponseMock(self.client.get(url, **self._clean_kwargs(kwargs)))
