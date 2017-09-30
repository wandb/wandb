import pytest
import os
from click.testing import CliRunner
import git
from wandb.git_repo import GitRepo


@pytest.fixture
def git_repo():
    with CliRunner().isolated_filesystem():
        r = git.Repo.init(".")
        open("README", "wb").close()
        r.index.add(["README"])
        r.index.commit("Initial commit")
        yield GitRepo(lazy=False)
