import pytest
import os
import click
from click.testing import CliRunner
import git
from wandb import cli
from wandb import api as wandb_api

import webbrowser
import whaaaaat
from wandb.git_repo import GitRepo


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(cli, 'api', wandb_api.Api(
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
