import pytest
import os
import click
from click.testing import CliRunner
import git
from wandb import cli
from wandb import util
from wandb.apis import InternalApi

import torch
import webbrowser
whaaaaat = util.vendor_import("whaaaaat")
from wandb.git_repo import GitRepo


PYTORCH_VERSION = tuple(int(i) for i in torch.__version__.split('.'))


if PYTORCH_VERSION < (0, 4):
    pytorch_tensor = torch.Tensor
else:
    # supports 0d tensors but is a module before 0.4
    pytorch_tensor = torch.tensor


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(cli, 'api', InternalApi(
        default_settings={'project': 'test', 'git_tag': True}, load_settings=False))
    monkeypatch.setattr(click, 'launch', lambda x: 1)
    monkeypatch.setattr(whaaaaat, 'prompt', lambda x: {
                        'project_name': 'test_model', 'files': ['weights.h5'],
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
