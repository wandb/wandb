from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import wandb

logger = logging.getLogger(__name__)

GIT_EXECUTABLE_ENV = "GIT_PYTHON_GIT_EXECUTABLE"


class GitCommandError(Exception):
    pass


@dataclass(frozen=True)
class GitTag:
    name: str


def git_error_output(error: subprocess.CalledProcessError) -> str:
    return error.stderr.decode(errors="replace")


def remote_url_without_password(url: str) -> str:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        return url

    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"

    if parsed.password is not None:
        return urlunparse(parsed._replace(netloc=f"{parsed.username}:@{hostname}"))

    return urlunparse(parsed._replace(netloc=hostname))


class GitRepo:
    def __init__(
        self,
        root: str | None = None,
        remote: str | None = "origin",
        lazy: bool = True,
        remote_url: str | None = None,
        commit: str | None = None,
        _git_executable: str | None = None,
    ) -> None:
        self.remote_name = remote if remote_url is None else None
        self._root = root
        self._remote_url = remote_url
        self._commit = commit
        self._git_executable = (
            _git_executable or os.environ.get(GIT_EXECUTABLE_ENV) or "git"
        )
        self._repo: str | None = None
        self._repo_initialized = False
        if not lazy:
            self._repo = self._init_repo()

    def _init_repo(self) -> str | None:
        self._repo_initialized = True
        if self.remote_name is None:
            return None

        try:
            return self.repo_root_for(self._root or os.getcwd())
        except FileNotFoundError as e:
            if e.filename == self._git_executable:
                logger.debug("git executable not found")
            elif self._root:
                wandb.termwarn(f"git root {self._root} does not exist")
                logger.warning(f"git root {self._root} does not exist")
            else:
                wandb.termwarn("current working directory has been invalidated")
                logger.warning("current working directory has been invalidated")
        except GitCommandError:
            logger.debug("git repository is invalid")
        return None

    @property
    def repo(self) -> str | None:
        if not self._repo_initialized:
            self._repo = self._init_repo()
        return self._repo

    def run_git(self, *args: str, cwd: str | None = None) -> str:
        if cwd is None:
            cwd = self.repo
            if cwd is None:
                raise GitCommandError("git repository is unavailable")

        try:
            proc = subprocess.run(
                [self._git_executable, *args],
                cwd=cwd,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise GitCommandError(git_error_output(e)) from e

        return proc.stdout.decode(errors="replace")

    def repo_root_for(self, cwd: str) -> str:
        return self.run_git("rev-parse", "--show-toplevel", cwd=cwd).strip()

    def untracked_files(self, pathspec: str) -> list[str]:
        output = self.run_git(
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            pathspec,
        )
        return [path for path in output.splitlines() if path]

    def has_tracked_changes(self) -> bool:
        return bool(
            self.run_git("status", "--porcelain", "--untracked-files=no").strip()
        )

    def config_value(self, name: str) -> str | None:
        value = self.run_git("config", "--get", name).strip()
        return value or None

    def commit_for_ref(self, ref: str) -> str:
        return self.run_git("rev-parse", "--verify", ref).strip()

    def current_branch(self) -> str:
        return self.run_git("symbolic-ref", "--short", "HEAD").strip()

    def remote_url_for(self, remote_name: str) -> str:
        return self.run_git("remote", "get-url", remote_name).strip()

    def remote_exists(self, remote_name: str) -> bool:
        try:
            self.remote_url_for(remote_name)
        except GitCommandError:
            return False
        else:
            return True

    def git_version(self) -> tuple[int, int, int] | None:
        output = self.run_git("--version")
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
        if match is None:
            return None
        return tuple(int(part) for part in match.groups())

    def is_detached_head(self) -> bool:
        try:
            self.run_git("symbolic-ref", "HEAD")
        except GitCommandError:
            return True
        else:
            return False

    def current_tracking_branch(self) -> str:
        return self.run_git("rev-parse", "--abbrev-ref", "@{upstream}").strip()

    def tracking_branches(self) -> list[str]:
        output = self.run_git(
            "for-each-ref",
            "--format=%(upstream:short)",
            "refs/heads/",
        )
        return list(dict.fromkeys(branch for branch in output.splitlines() if branch))

    def merge_base(self, *refs: str) -> str:
        return self.run_git("merge-base", *refs).strip()

    def is_ancestor(self, older: str, newer: str) -> bool:
        try:
            self.run_git("merge-base", "--is-ancestor", older, newer)
        except GitCommandError:
            return False
        else:
            return True

    def create_tag(self, tag_name: str, message: str | None) -> None:
        args = ["tag", "-f"]
        if message is not None:
            args.extend(["-m", message])
        args.append(tag_name)
        self.run_git(*args)

    @property
    def auto(self) -> bool:
        return self._remote_url is None

    def is_untracked(self, file_name: str) -> bool | None:
        if not self.repo:
            return True
        try:
            return bool(self.untracked_files(file_name))
        except GitCommandError:
            return None

    @property
    def enabled(self) -> bool:
        return bool(self.repo)

    @property
    def dirty(self) -> Any:
        if not self.repo:
            return False
        try:
            return self.has_tracked_changes()
        except GitCommandError:
            return False

    @property
    def email(self) -> str | None:
        if not self.repo:
            return None
        try:
            return self.config_value("user.email")
        except GitCommandError:
            return None

    @property
    def last_commit(self) -> Any:
        if self._commit:
            return self._commit
        if not self.repo:
            return None
        try:
            return self.commit_for_ref("HEAD")
        except GitCommandError:
            logger.debug("Unable to find most recent commit in git")
            return None

    @property
    def branch(self) -> Any:
        if not self.repo:
            return None
        try:
            return self.current_branch()
        except GitCommandError:
            return None

    @property
    def remote(self) -> Any:
        if not self.repo or not self.remote_name:
            return None
        if not self.remote_exists(self.remote_name):
            return None
        return self.remote_name

    # the --submodule=diff option doesn't exist in pre-2.11 versions of git (november 2016)
    # https://stackoverflow.com/questions/10757091/git-list-of-all-changed-files-including-those-in-submodules
    @property
    def has_submodule_diff(self) -> bool:
        if not self.repo:
            return False
        try:
            version = self.git_version()
        except GitCommandError:
            return False
        return version is not None and version >= (2, 11, 0)

    @property
    def remote_url(self) -> Any:
        if self._remote_url:
            return self._remote_url
        if not self.repo or not self.remote_name:
            return None
        try:
            return remote_url_without_password(self.remote_url_for(self.remote_name))
        except GitCommandError:
            return None

    def get_upstream_fork_point(self) -> Any:
        """Get the most recent ancestor of HEAD that occurs on an upstream branch.

        First looks at the current branch's tracking branch, if applicable. If
        that doesn't work, looks at every other branch to find the most recent
        ancestor of HEAD that occurs on a tracking branch.

        Returns:
            Commit hash string or None
        """
        try:
            if not self.repo:
                return None
            if self.is_detached_head():
                logger.debug("git is in a detached head state")
                return None

            possible_relatives = []
            try:
                possible_relatives.append(self.current_tracking_branch())
            except GitCommandError:
                pass

            if not possible_relatives:
                possible_relatives = self.tracking_branches()

            most_recent_ancestor = None
            for possible_relative in possible_relatives:
                try:
                    ancestor = self.merge_base("HEAD", possible_relative)
                except GitCommandError:
                    continue
                if most_recent_ancestor is None or self.is_ancestor(
                    most_recent_ancestor, ancestor
                ):
                    most_recent_ancestor = ancestor
        except GitCommandError as e:
            logger.debug("git remote upstream fork point could not be found")
            logger.debug(str(e))
            return None

        return most_recent_ancestor

    def fetch_all(self) -> None:
        self.run_git("fetch", "--all")

    def has_commit(self, commit: str) -> bool:
        try:
            self.run_git("cat-file", "-e", f"{commit}^{{commit}}")
        except GitCommandError:
            return False
        else:
            return True

    def has_branch(self, branch_name: str) -> bool:
        try:
            self.run_git(
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch_name}",
            )
        except GitCommandError:
            return False
        else:
            return True

    def checkout(self, ref: str) -> None:
        self.run_git("checkout", ref)

    def checkout_new_branch(self, branch_name: str, start_point: str) -> None:
        self.run_git("checkout", "-b", branch_name, start_point)

    def tag(self, name: str, message: str | None) -> Any:
        if not self.repo:
            return None
        tag_name = f"wandb/{name}"
        try:
            self.create_tag(tag_name, message)
            return GitTag(tag_name)
        except GitCommandError:
            logger.debug("Failed to tag repository.")
            return None

    def push(self, name: str) -> Any:
        if not self.remote:
            return None
        try:
            return self.run_git(
                "push",
                self.remote_name or "origin",
                f"wandb/{name}",
                "--force",
            )
        except GitCommandError:
            logger.debug("failed to push git")
            return None
