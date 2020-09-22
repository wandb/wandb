#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
test_git_repo
----------------------------------

Tests for the `wandb.GitRepo` module.
"""
import platform
import pytest
from wandb.lib.git import GitRepo


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
