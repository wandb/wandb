"""Tests for `GitReference.fetch` against real local git repositories."""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from wandb.sdk.launch import git_reference as git_reference_module
from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.launch.git_reference import GitReference


def run_git(cwd: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


@pytest.fixture
def uri_recorder(monkeypatch) -> list[tuple[str, ...]]:
    """Record the args of every ``run_git`` call while still calling through."""
    calls: list[tuple[str, ...]] = []
    real_run_git = git_reference_module.run_git

    def spy(*args: str, **kwargs):
        calls.append(args)
        return real_run_git(*args, **kwargs)

    monkeypatch.setattr(git_reference_module, "run_git", spy)
    return calls


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


@pytest.mark.parametrize(
    "uri",
    [
        "ext::sh -c 'touch /tmp/pwned'",
        "EXT::sh -c 'touch /tmp/pwned'",
        "fd::17/foo",
        "file:///tmp/evil.git",
        "-u./payload",
        "--upload-pack=touch /tmp/pwned",
    ],
)
def test_fetch_rejects_dangerous_uri(uri, tmp_path):
    """Command-executing transports and option-like remotes are refused."""
    ref = GitReference(uri)

    with pytest.raises(LaunchError, match="Refusing to fetch git remote"):
        ref.fetch(str(tmp_path / "dst"))


def test_fetch_dangerous_uri_runs_no_git(uri_recorder, tmp_path):
    """A rejected URI is refused before any git process is spawned."""
    ref = GitReference("ext::sh -c 'touch /tmp/pwned'")

    with pytest.raises(LaunchError):
        ref.fetch(str(tmp_path / "dst"))

    assert uri_recorder == []


def test_fetch_blocked_submodule_raises_launch_error(source_repo, tmp_path):
    """A submodule over a forbidden transport is blocked and reported cleanly."""
    # Point a submodule at a file:// URL; our protocol allowlist refuses it.
    evil = tmp_path / "evil"
    subprocess.run(
        ["git", "init", "--initial-branch", "main", evil],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    run_git(evil, "config", "user.name", "test")
    run_git(evil, "config", "user.email", "test@test.com")
    (evil / "payload").write_text("x\n")
    run_git(evil, "add", "payload")
    run_git(evil, "commit", "--no-verify", "--no-gpg-sign", "-m", "evil")
    run_git(
        source_repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        f"file://{evil}",
        "sub",
    )
    run_git(
        source_repo, "commit", "--no-verify", "--no-gpg-sign", "-m", "add submodule"
    )

    ref = GitReference(str(source_repo))

    with pytest.raises(LaunchError, match="Unable to update submodules"):
        ref.fetch(str(tmp_path / "dst"))


def test_fetch_hardens_transports(source_repo, tmp_path, uri_recorder):
    """The fetch and recursive-submodule calls pin the protocol allowlist."""
    ref = GitReference(str(source_repo))

    ref.fetch(str(tmp_path / "dst"))

    fetch_calls = [args for args in uri_recorder if "fetch" in args]
    submodule_calls = [args for args in uri_recorder if "submodule" in args]

    assert fetch_calls, "expected a git fetch"
    assert all("protocol.ext.allow=never" in args for args in fetch_calls)

    assert submodule_calls, "expected a git submodule update"
    for args in submodule_calls:
        assert "protocol.file.allow=never" in args
        assert "protocol.ext.allow=never" in args
