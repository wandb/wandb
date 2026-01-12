#!/usr/bin/env python

"""Tests for the `wandb.GitRepo` module."""

from __future__ import annotations

from collections.abc import Generator

import git
import pytest
from wandb.sdk.lib.gitlib import GitRepo


@pytest.fixture
def git_repo_fn() -> Generator:
    def git_repo_fn_helper(
        path: str = ".",
        remote_name: str = "origin",
        remote_url: str | None = "https://foo:bar@github.com/FooTest/Foo.git",
        commit_msg: str | None = None,
    ):
        with git.Repo.init(path) as repo:
            if remote_url is not None:
                repo.create_remote(remote_name, remote_url)
            if commit_msg is not None:
                repo.index.commit(commit_msg)
            return GitRepo(lazy=False)

    yield git_repo_fn_helper


class TestGitRepo:
    def test_last_commit(self, git_repo_fn):
        git_repo = git_repo_fn(commit_msg="My commit message")
        assert len(git_repo.last_commit) == 40

    def test_dirty(self, git_repo_fn):
        git_repo = git_repo_fn()
        assert not git_repo.dirty
        open("foo.txt", "wb").close()
        git_repo.repo.index.add(["foo.txt"])
        assert git_repo.dirty

    def test_remote_url(self, git_repo_fn):
        repo = git_repo_fn(remote_url=None)
        assert repo.remote_url is None

    def test_create_tag(self, git_repo_fn):
        # TODO: assert git / not git
        git_repo = git_repo_fn()
        tag = git_repo.tag("foo", "My great tag")
        assert tag is None or tag.name == "wandb/foo"

    def test_no_repo(self):
        assert not GitRepo(root="/tmp").enabled

    def test_no_remote(self):
        assert not GitRepo(remote=None).enabled

    def test_manual(self):
        remote_url = "https://foo@github.com/FooTest/Foo.git"
        commit = "29c15e893e36efad84001f4484b4813fbacd55a0"
        git_repo = GitRepo(remote_url=remote_url, commit=commit)
        assert not git_repo.auto
        assert git_repo.last_commit == commit
        assert git_repo.remote_url == remote_url

    def test_remote_url_with_token(self, git_repo_fn):
        remote_url = "https://foo:bar@github.com/FooTest/Foo.git"
        git_repo = git_repo_fn(remote_url=remote_url)
        assert "bar" not in git_repo.remote_url
        assert git_repo.remote_url is not None

    def test_remote_url_no_token(self, git_repo_fn):
        remote_url = "https://foo:@github.com/FooTest/Foo.git"
        git_repo = git_repo_fn(remote_url=remote_url)

        assert git_repo.remote_url == remote_url

    def test_remote_with_port(self, git_repo_fn):
        remote_url = "https://foo:@github.com:8080/FooTest/Foo.git"
        git_repo = git_repo_fn(remote_url=remote_url)
        assert git_repo.remote_url == remote_url

    def test_root_doesnt_exist(self):
        git_repo = GitRepo(root="/tmp/foo")
        assert git_repo.repo is None and git_repo._repo_initialized is True
