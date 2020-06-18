#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_git_repo
----------------------------------

Tests for the `wandb.GitRepo` module.
"""
from click.testing import CliRunner
import git
import os
import platform
import pytest

from wandb.internal.git_repo import GitRepo


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


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="GitRepo lib doesn't work in circleci windows",
)
class TestGitRepo:
    def test_last_commit(self, git_repo):
        assert len(git_repo.last_commit) == 40

    def test_dirty(self, git_repo):
        assert not git_repo.dirty
        open("foo.txt", "wb").close()
        git_repo.repo.index.add(["foo.txt"])
        assert git_repo.dirty

    def test_remote_url(self, git_repo):
        assert git_repo.remote_url is None

    def test_create_tag(self, git_repo):
        # TODO: assert git / not git
        tag = git_repo.tag("foo", "My great tag")
        assert tag is None or tag.name == "wandb/foo"

    def test_no_repo(self):
        assert not GitRepo(root="/tmp").enabled

    def test_no_remote(self):
        assert not GitRepo(remote=None).enabled
