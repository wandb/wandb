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
def allow_local(monkeypatch) -> None:
    """Let behavior tests fetch from local fixtures.

    Production only allows https/ssh remotes and pins ``protocol.file.allow=never``,
    so exercising the real fetch/checkout logic against a local repo requires
    relaxing both the scheme allowlist and the file-transport hardening.
    """
    monkeypatch.setattr(git_reference_module, "_validate_uri", lambda uri: None)
    monkeypatch.setattr(
        git_reference_module,
        "_PROTOCOL_HARDENING",
        ("-c", "protocol.file.allow=always"),
    )


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


def test_fetch_default_branch(source_repo, tmp_path, allow_local):
    dst_dir = tmp_path / "dst"
    ref = GitReference(str(source_repo))

    ref.fetch(str(dst_dir))

    assert ref.default_branch == "main"
    assert ref.ref == "main"
    assert ref.path == str(dst_dir)
    assert ref.commit_hash == run_git(source_repo, "rev-parse", "main")


def test_fetch_branch(source_repo, tmp_path, allow_local):
    dst_dir = tmp_path / "dst"
    ref = GitReference(str(source_repo), "feature")

    ref.fetch(str(dst_dir))

    assert ref.commit_hash == run_git(source_repo, "rev-parse", "feature")
    assert (dst_dir / "feature.py").exists()


def test_fetch_commit_hash(source_repo, tmp_path, allow_local):
    dst_dir = tmp_path / "dst"
    commit = run_git(source_repo, "rev-parse", "main")
    ref = GitReference(str(source_repo), commit)

    ref.fetch(str(dst_dir))

    assert ref.commit_hash == commit
    assert not (dst_dir / "feature.py").exists()


def test_fetch_bad_remote_raises_launch_error(tmp_path, allow_local):
    ref = GitReference(str(tmp_path / "does-not-exist"))

    with pytest.raises(LaunchError, match="Unable to fetch"):
        ref.fetch(str(tmp_path / "dst"))


def test_fetch_without_git_raises_launch_error(tmp_path, allow_local, monkeypatch):
    monkeypatch.setenv("GIT_PYTHON_GIT_EXECUTABLE", "git-not-found")
    ref = GitReference(str(tmp_path / "source"))

    with pytest.raises(LaunchError, match="Unable to fetch"):
        ref.fetch(str(tmp_path / "dst"))


def test_fetch_no_default_branch_raises_launch_error(
    source_repo, tmp_path, allow_local
):
    run_git(source_repo, "branch", "-m", "main", "trunk")
    ref = GitReference(str(source_repo))

    with pytest.raises(LaunchError, match="Unable to determine branch or commit"):
        ref.fetch(str(tmp_path / "dst"))


@pytest.mark.parametrize(
    "uri",
    [
        "https://github.com/wandb/launch-jobs",
        "https://github.com/wandb/launch-jobs.git",
        "ssh://git@github.com/wandb/launch-jobs.git",
        "git@github.com:wandb/launch-jobs.git",
        "git@host.example.com:group/sub/repo.git",
    ],
)
def test_validate_uri_allows_supported_remotes(uri):
    """https, ssh, and scp-like git@host:path remotes are permitted."""
    git_reference_module._validate_uri(uri)  # does not raise


@pytest.mark.parametrize(
    "uri",
    [
        "file:///tmp/some/repo.git",
        "ext::sh -c 'echo hi'",
        "EXT::sh -c 'echo hi'",
        "fd::17/foo",
        "git://github.com/wandb/launch-jobs.git",
        "http://github.com/wandb/launch-jobs.git",
        "/tmp/local/repo",
        ".",
        "./relative/repo",
        "-u./x",
        "--upload-pack=echo",
        "-x@host:path",
    ],
)
def test_validate_uri_rejects_everything_else(uri):
    """file/ext/fd/git/http, bare paths, and option-like remotes are refused."""
    with pytest.raises(LaunchError, match="Refusing to fetch git remote"):
        git_reference_module._validate_uri(uri)


def test_fetch_rejected_uri_runs_no_git(uri_recorder, tmp_path):
    """A rejected remote is refused before any git process is spawned."""
    ref = GitReference("ext::sh -c 'echo hi'")

    with pytest.raises(LaunchError, match="Refusing to fetch git remote"):
        ref.fetch(str(tmp_path / "dst"))

    assert uri_recorder == []


def test_protocol_hardening_pins_file_and_ext():
    """The hardening applied to git commands denies the file and ext transports."""
    assert git_reference_module._PROTOCOL_HARDENING == (
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
    )


def test_fetch_hardens_fetch_and_submodule(monkeypatch, tmp_path):
    """fetch() pins the protocol allowlist on both the fetch and submodule calls."""
    monkeypatch.setattr(git_reference_module, "_validate_uri", lambda uri: None)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        git_reference_module, "run_git", lambda *a, **k: calls.append(a) or ""
    )

    GitReference("https://example.com/o/r.git").fetch(str(tmp_path / "dst"))

    fetch_calls = [a for a in calls if "fetch" in a]
    submodule_calls = [a for a in calls if "submodule" in a]
    assert fetch_calls, "expected a git fetch"
    assert submodule_calls, "expected a git submodule update"
    for group in (fetch_calls, submodule_calls):
        for args in group:
            assert "protocol.file.allow=never" in args
            assert "protocol.ext.allow=never" in args


def test_fetch_blocked_submodule_raises_launch_error(
    source_repo, tmp_path, monkeypatch
):
    """A submodule over the file transport is blocked and reported cleanly."""
    monkeypatch.setattr(git_reference_module, "_validate_uri", lambda uri: None)
    # Allow the top-level local fetch (user context) while keeping the recursive
    # submodule fetch restricted, mirroring the production file.allow=never
    # posture for recursion.
    monkeypatch.setattr(
        git_reference_module, "_PROTOCOL_HARDENING", ("-c", "protocol.file.allow=user")
    )

    submodule_src = tmp_path / "submodule_src"
    subprocess.run(
        ["git", "init", "--initial-branch", "main", submodule_src],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    run_git(submodule_src, "config", "user.name", "test")
    run_git(submodule_src, "config", "user.email", "test@test.com")
    (submodule_src / "data").write_text("x\n")
    run_git(submodule_src, "add", "data")
    run_git(submodule_src, "commit", "--no-verify", "--no-gpg-sign", "-m", "init")
    run_git(
        source_repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        f"file://{submodule_src}",
        "sub",
    )
    run_git(
        source_repo, "commit", "--no-verify", "--no-gpg-sign", "-m", "add submodule"
    )

    ref = GitReference(str(source_repo))

    with pytest.raises(LaunchError, match="Unable to update submodules"):
        ref.fetch(str(tmp_path / "dst"))
