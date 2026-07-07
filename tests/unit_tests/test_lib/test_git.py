#!/usr/bin/env python

"""Tests for the `wandb.GitRepo` module."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Generator

import pytest
from wandb.sdk.lib import gitlib
from wandb.sdk.lib.gitlib import GitCommandError, GitRepo, GitVersion


def run_git(cwd: str, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def init_git_repo(path: str) -> None:
    subprocess.run(["git", "init", path], check=True, stdout=subprocess.DEVNULL)
    run_git(path, "config", "user.name", "test")
    run_git(path, "config", "user.email", "test@test.com")


def add_remote(path: str, name: str, url: str) -> None:
    run_git(path, "remote", "add", name, url)


def commit_empty(path: str, message: str) -> None:
    # Skip hooks and signing so the user's git config can't break tests.
    run_git(
        path, "commit", "--no-verify", "--no-gpg-sign", "--allow-empty", "-m", message
    )


def stage_file(path: str, file_name: str) -> None:
    run_git(path, "add", file_name)


def initialized_git_repo(root: str = "/repo") -> GitRepo:
    git_repo = GitRepo(root=root)
    git_repo._root_dir = root
    git_repo._root_dir_initialized = True
    return git_repo


def raise_git_error(*args, **kwargs):
    raise GitCommandError("git failed")


@pytest.fixture
def git_repo_fn() -> Generator:
    def git_repo_fn_helper(
        path: str = ".",
        remote_name: str = "origin",
        remote_url: str | None = "https://foo:bar@github.com/FooTest/Foo.git",
        commit_msg: str | None = None,
    ):
        init_git_repo(path)
        if remote_url is not None:
            add_remote(path, remote_name, remote_url)
        if commit_msg is not None:
            commit_empty(path, commit_msg)
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
        assert git_repo.root_dir is not None
        stage_file(git_repo.root_dir, "foo.txt")
        assert git_repo.dirty

    def test_remote_url(self, git_repo_fn):
        repo = git_repo_fn(remote_url=None)
        assert repo.remote_url is None

    def test_create_tag(self, git_repo_fn):
        # TODO: assert git / not git
        git_repo = git_repo_fn()
        tag = git_repo.tag("foo", "My great tag")
        assert tag is None or tag == "wandb/foo"

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

    def test_root_doesnt_exist(self, tmp_path):
        git_repo = GitRepo(root=str(tmp_path / "nonexistent"))
        assert git_repo.root_dir is None and git_repo._root_dir_initialized is True

    def test_git_version(self, monkeypatch):
        git_repo = GitRepo(remote=None)
        monkeypatch.setattr(
            git_repo,
            "run_git",
            lambda *args, **kwargs: "git version 2.50.1 (Apple Git-155)",
        )

        assert git_repo.git_version() == GitVersion(2, 50, 1)

    def test_git_version_unparseable(self, monkeypatch):
        git_repo = GitRepo(remote=None)
        monkeypatch.setattr(git_repo, "run_git", lambda *args, **kwargs: "git")

        assert git_repo.git_version() is None

    def test_run_git_requires_repo(self):
        with pytest.raises(GitCommandError, match="git repository is unavailable"):
            GitRepo(remote=None).run_git("status")

    def test_run_git_raises_command_error(self, tmp_path):
        with pytest.raises(GitCommandError, match="not-a-git-command"):
            GitRepo().run_git("not-a-git-command", cwd=str(tmp_path))

    def test_run_git_missing_executable_raises_command_error(self):
        with pytest.raises(GitCommandError, match="failed to run"):
            gitlib.run_git("--version", executable="git-not-found")

    def test_run_git_unusable_executable_raises_command_error(self, tmp_path):
        with pytest.raises(GitCommandError, match="failed to run"):
            gitlib.run_git("--version", executable=str(tmp_path))

    def test_run_git_ignores_repo_override_env(self, tmp_path, monkeypatch):
        repo_path = str(tmp_path / "repo")
        init_git_repo(repo_path)
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))

        root_dir = GitRepo(root=repo_path).root_dir

        assert root_dir is not None
        assert os.path.realpath(root_dir) == os.path.realpath(repo_path)

    def test_init_repo_without_git(self):
        git_repo = GitRepo(lazy=False, _git_executable="git-not-found")

        assert git_repo.root_dir is None

    def test_init_repo_invalid_current_directory(self, monkeypatch):
        def getcwd():
            raise FileNotFoundError()

        monkeypatch.setattr(os, "getcwd", getcwd)

        assert GitRepo(lazy=False).root_dir is None

    def test_init_repo_invalid_git_repository(self, tmp_path):
        git_repo = GitRepo(root=str(tmp_path), lazy=False)

        assert git_repo.root_dir is None

    def test_git_command_helpers(self, monkeypatch):
        git_repo = initialized_git_repo()
        commands = []
        outputs = {
            ("rev-parse", "--show-toplevel"): "/repo\n",
            ("ls-files", "--others", "--exclude-standard", "--", "*.py"): (
                "a.py\n\nb.py\n"
            ),
            ("status", "--porcelain", "--untracked-files=no"): " M file.py\n",
            ("config", "--get", "user.email"): "test@example.com\n",
            ("config", "--get", "missing"): "\n",
            ("rev-parse", "--verify", "HEAD"): "abc123\n",
            ("symbolic-ref", "--short", "HEAD"): "main\n",
            (
                "config",
                "--get",
                "remote.origin.url",
            ): "https://github.com/wandb/wandb.git\n",
            ("--version",): "git version 2.50.1\n",
            ("symbolic-ref", "HEAD"): "refs/heads/main\n",
            ("rev-parse", "--abbrev-ref", "@{upstream}"): "origin/main\n",
            (
                "for-each-ref",
                "--format=%(upstream:short)",
                "refs/heads/",
            ): "origin/main\n\norigin/main\norigin/dev\n",
            ("merge-base", "HEAD", "origin/main"): "base123\n",
        }

        def fake_run_git(*args, **kwargs):
            commands.append(args)
            return outputs.get(args, "")

        monkeypatch.setattr(git_repo, "run_git", fake_run_git)

        assert git_repo.repo_root_for("/repo") == "/repo"
        assert git_repo.untracked_files("*.py") == ["a.py", "b.py"]
        assert git_repo.is_untracked("*.py")
        assert git_repo.has_tracked_changes()
        assert git_repo.config_value("user.email") == "test@example.com"
        assert git_repo.config_value("missing") is None
        assert git_repo.commit_for_ref("HEAD") == "abc123"
        assert git_repo.current_branch() == "main"
        assert git_repo.remote_url_for("origin") == "https://github.com/wandb/wandb.git"
        assert git_repo.remote_exists("origin")
        assert git_repo.email == "test@example.com"
        assert git_repo.last_commit == "abc123"
        assert git_repo.branch == "main"
        assert git_repo.remote == "origin"
        assert git_repo.remote_url == "https://github.com/wandb/wandb.git"
        assert git_repo.has_submodule_diff
        assert not git_repo.is_detached_head()
        assert git_repo.current_tracking_branch() == "origin/main"
        assert git_repo.tracking_branches() == ["origin/main", "origin/dev"]
        assert git_repo.merge_base("HEAD", "origin/main") == "base123"
        assert git_repo.is_ancestor("base", "HEAD")
        assert git_repo.has_commit("abc123")
        assert git_repo.has_branch("main")

        git_repo.fetch_all()
        git_repo.create_tag("wandb/with-message", "message")
        git_repo.create_tag("wandb/no-message", None)
        git_repo.checkout("main")
        git_repo.checkout_new_branch("feature", "main")
        assert git_repo.push("name") == ""

        assert ("fetch", "--all") in commands
        assert ("tag", "-f", "-m", "message", "wandb/with-message") in commands
        assert ("tag", "-f", "wandb/no-message") in commands
        assert ("checkout", "main") in commands
        assert ("checkout", "-b", "feature", "main") in commands
        assert ("push", "origin", "wandb/name", "--force") in commands

    def test_git_command_helpers_handle_errors(self, monkeypatch):
        git_repo = initialized_git_repo()
        monkeypatch.setattr(git_repo, "run_git", raise_git_error)

        assert not git_repo.remote_exists("origin")
        assert git_repo.is_detached_head()
        assert not git_repo.is_ancestor("base", "HEAD")
        assert not git_repo.has_commit("abc123")
        assert not git_repo.has_branch("main")

    def test_git_state_properties_handle_errors(self, monkeypatch):
        git_repo = initialized_git_repo()

        monkeypatch.setattr(git_repo, "untracked_files", raise_git_error)
        assert git_repo.is_untracked("file.py") is None

        monkeypatch.setattr(git_repo, "has_tracked_changes", raise_git_error)
        assert not git_repo.dirty

        monkeypatch.setattr(git_repo, "config_value", raise_git_error)
        assert git_repo.email is None

        monkeypatch.setattr(git_repo, "commit_for_ref", raise_git_error)
        assert git_repo.last_commit is None

        monkeypatch.setattr(git_repo, "current_branch", raise_git_error)
        assert git_repo.branch is None

        monkeypatch.setattr(git_repo, "remote_exists", lambda *args: False)
        assert git_repo.remote is None

        monkeypatch.setattr(git_repo, "git_version", raise_git_error)
        assert not git_repo.has_submodule_diff

        monkeypatch.setattr(git_repo, "remote_url_for", raise_git_error)
        assert git_repo.remote_url is None

        monkeypatch.setattr(git_repo, "create_tag", raise_git_error)
        assert git_repo.tag("name", "message") is None

        monkeypatch.setattr(git_repo, "remote_exists", lambda *args: True)
        monkeypatch.setattr(git_repo, "run_git", raise_git_error)
        assert git_repo.push("name") is None

    def test_has_submodule_diff(self, monkeypatch):
        git_repo = initialized_git_repo()

        monkeypatch.setattr(git_repo, "git_version", lambda: GitVersion(2, 10, 9))
        assert not git_repo.has_submodule_diff

        monkeypatch.setattr(git_repo, "git_version", lambda: GitVersion(2, 11, 0))
        assert git_repo.has_submodule_diff

    def test_get_upstream_fork_point_uses_tracking_branch(self, monkeypatch):
        git_repo = initialized_git_repo()
        monkeypatch.setattr(git_repo, "is_detached_head", lambda: False)
        monkeypatch.setattr(git_repo, "current_tracking_branch", lambda: "origin/main")
        monkeypatch.setattr(git_repo, "merge_base", lambda *args: "base123")

        assert git_repo.get_upstream_fork_point() == "base123"

    def test_get_upstream_fork_point_searches_tracking_branches(self, monkeypatch):
        git_repo = initialized_git_repo()
        ancestors = {"origin/old": "old123", "origin/new": "new123"}
        monkeypatch.setattr(git_repo, "is_detached_head", lambda: False)
        monkeypatch.setattr(git_repo, "current_tracking_branch", raise_git_error)
        monkeypatch.setattr(
            git_repo,
            "tracking_branches",
            lambda: ["origin/bad", "origin/old", "origin/new"],
        )

        def merge_base(head, branch):
            if branch == "origin/bad":
                raise GitCommandError("no merge base")
            return ancestors[branch]

        monkeypatch.setattr(git_repo, "merge_base", merge_base)
        monkeypatch.setattr(
            git_repo,
            "is_ancestor",
            lambda older, newer: older == "old123" and newer == "new123",
        )

        assert git_repo.get_upstream_fork_point() == "new123"

    def test_get_upstream_fork_point_detached(self, monkeypatch):
        git_repo = initialized_git_repo()
        monkeypatch.setattr(git_repo, "is_detached_head", lambda: True)

        assert git_repo.get_upstream_fork_point() is None

    def test_get_upstream_fork_point_handles_git_error(self, monkeypatch):
        git_repo = initialized_git_repo()
        monkeypatch.setattr(git_repo, "is_detached_head", raise_git_error)

        assert git_repo.get_upstream_fork_point() is None
