#!/usr/bin/env python

"""Tests for the `wandb.GitRepo` module."""
from typing import Callable, Optional

import git
import pytest
import wandb

GitRepo = wandb.wandb_lib.git.GitRepo


@pytest.fixture
def git_repo_fn() -> Callable:
    def git_repo_fn_helper(
        path: str = ".",
        remote_name: str = "origin",
        remote_url: Optional[str] = "https://foo:bar@github.com/FooTest/Foo.git",
        commit_msg: Optional[str] = None,
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
