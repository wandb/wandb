"""Tests for `GitReference.fetch` against real local git repositories."""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.git_reference import GitReference


def run_git(cwd: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


@pytest.fixture
def source_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A local git repo with a `main` branch and a `feature` branch."""
    path = tmp_path / "source"
    subprocess.run(
        ["git", "init", "--initial-branch", "main", path],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    run_git(path, "config", "user.name", "test")
    run_git(path, "config", "user.email", "test@test.com")
    (path / "main.py").write_text("print('hello')\n")
    run_git(path, "add", "main.py")
    # Skip hooks and signing so the user's git config can't break tests.
    run_git(path, "commit", "--no-verify", "--no-gpg-sign", "-m", "Initial commit")
    run_git(path, "checkout", "-b", "feature")
    (path / "feature.py").write_text("print('feature')\n")
    run_git(path, "add", "feature.py")
    run_git(path, "commit", "--no-verify", "--no-gpg-sign", "-m", "Feature commit")
    run_git(path, "checkout", "main")
    return path


def test_fetch_default_branch(source_repo, tmp_path):
    dst_dir = tmp_path / "dst"
    ref = GitReference(str(source_repo))

    ref.fetch(str(dst_dir))

    assert ref.default_branch == "main"
    assert ref.ref == "main"
    assert ref.path == str(dst_dir)
    assert ref.commit_hash == run_git(source_repo, "rev-parse", "main")


def test_fetch_branch(source_repo, tmp_path):
    dst_dir = tmp_path / "dst"
    ref = GitReference(str(source_repo), "feature")

    ref.fetch(str(dst_dir))

    assert ref.commit_hash == run_git(source_repo, "rev-parse", "feature")
    assert (dst_dir / "feature.py").exists()


def test_fetch_commit_hash(source_repo, tmp_path):
    dst_dir = tmp_path / "dst"
    commit = run_git(source_repo, "rev-parse", "main")
    ref = GitReference(str(source_repo), commit)

    ref.fetch(str(dst_dir))

    assert ref.commit_hash == commit
    assert not (dst_dir / "feature.py").exists()


def test_fetch_bad_remote_raises_launch_error(tmp_path):
    ref = GitReference(str(tmp_path / "does-not-exist"))

    with pytest.raises(LaunchError, match="Unable to fetch"):
        ref.fetch(str(tmp_path / "dst"))


def test_fetch_without_git_raises_launch_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_PYTHON_GIT_EXECUTABLE", "git-not-found")
    ref = GitReference(str(tmp_path / "source"))

    with pytest.raises(LaunchError, match="Unable to fetch"):
        ref.fetch(str(tmp_path / "dst"))


def test_fetch_no_default_branch_raises_launch_error(source_repo, tmp_path):
    run_git(source_repo, "branch", "-m", "main", "trunk")
    ref = GitReference(str(source_repo))

    with pytest.raises(LaunchError, match="Unable to determine branch or commit"):
        ref.fetch(str(tmp_path / "dst"))
