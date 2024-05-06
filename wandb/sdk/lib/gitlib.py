import configparser
import logging
import os
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse, urlunparse

import wandb

try:
    from git import (  # type: ignore
        GitCommandError,
        InvalidGitRepositoryError,
        NoSuchPathError,
        Repo,
    )
except ImportError:
    Repo = None  # type: ignore

if TYPE_CHECKING:
    from git import Repo


logger = logging.getLogger(__name__)


class GitRepo:
    def __init__(
        self,
        root: Optional[str] = None,
        remote: str = "origin",
        lazy: bool = True,
        remote_url: Optional[str] = None,
        commit: Optional[str] = None,
    ) -> None:
        self.remote_name = remote if remote_url is None else None
        self._root = root
        self._remote_url = remote_url
        self._commit = commit
        self._repo = None
        self._repo_initialized = False
        if not lazy:
            self._repo = self._init_repo()

    def _init_repo(self) -> Optional[Repo]:
        self._repo_initialized = True
        if Repo is None:
            return None
        if self.remote_name is None:
            return None
        try:
            return Repo(self._root or os.getcwd(), search_parent_directories=True)
        except FileNotFoundError:
            wandb.termwarn("current working directory has been invalidated")
            logger.warn("current working directory has been invalidated")
        except InvalidGitRepositoryError:
            logger.debug("git repository is invalid")
        except NoSuchPathError:
            wandb.termwarn(f"git root {self._root} does not exist")
            logger.warn(f"git root {self._root} does not exist")
        return None

    @property
    def repo(self) -> Optional[Repo]:
        if not self._repo_initialized:
            self._repo = self._init_repo()
        return self._repo

    @property
    def auto(self) -> bool:
        return self._remote_url is None

    def is_untracked(self, file_name: str) -> Optional[bool]:
        if not self.repo:
            return True
        try:
            return file_name in self.repo.untracked_files
        except GitCommandError:
            return None

    @property
    def enabled(self) -> bool:
        return bool(self.repo)

    @property
    def root(self) -> Any:
        if not self.repo:
            return None
        try:
            return self.repo.git.rev_parse("--show-toplevel")
        except GitCommandError as e:
            # todo: collect telemetry on this
            logger.error(f"git root error: {e}")
            return None

    @property
    def dirty(self) -> Any:
        if not self.repo:
            return False
        try:
            return self.repo.is_dirty()
        except GitCommandError:
            return False

    @property
    def email(self) -> Optional[str]:
        if not self.repo:
            return None
        try:
            return self.repo.config_reader().get_value("user", "email")  # type: ignore
        except configparser.Error:
            return None

    @property
    def last_commit(self) -> Any:
        if self._commit:
            return self._commit
        if not self.repo:
            return None
        if not self.repo.head or not self.repo.head.is_valid():
            return None
        # TODO: Saw a user getting a Unicode decode error when parsing refs,
        # more details on implementing a real fix in [WB-4064]
        try:
            if len(self.repo.refs) > 0:  # type: ignore[arg-type]
                return self.repo.head.commit.hexsha
            else:
                return self.repo.git.show_ref("--head").split(" ")[0]
        except Exception:
            logger.exception("Unable to find most recent commit in git")
            return None

    @property
    def branch(self) -> Any:
        if not self.repo:
            return None
        return self.repo.head.ref.name

    @property
    def remote(self) -> Any:
        if not self.repo:
            return None
        try:
            return self.repo.remotes[self.remote_name]  # type: ignore[index]
        except IndexError:
            return None

    # the --submodule=diff option doesn't exist in pre-2.11 versions of git (november 2016)
    # https://stackoverflow.com/questions/10757091/git-list-of-all-changed-files-including-those-in-submodules
    @property
    def has_submodule_diff(self) -> bool:
        if not self.repo:
            return False
        return bool(self.repo.git.version_info >= (2, 11, 0))

    @property
    def remote_url(self) -> Any:
        if self._remote_url:
            return self._remote_url
        if not self.remote:
            return None
        parsed = urlparse(self.remote.url)
        hostname = parsed.hostname
        if parsed.port is not None:
            hostname = f"{hostname}:{parsed.port}"
        if parsed.password is not None:
            return urlunparse(parsed._replace(netloc=f"{parsed.username}:@{hostname}"))
        return urlunparse(parsed._replace(netloc=hostname))

    @property
    def root_dir(self) -> Any:
        if not self.repo:
            return None
        try:
            return self.repo.git.rev_parse("--show-toplevel")
        except GitCommandError:
            return None

    def get_upstream_fork_point(self) -> Any:
        """Get the most recent ancestor of HEAD that occurs on an upstream branch.

        First looks at the current branch's tracking branch, if applicable. If
        that doesn't work, looks at every other branch to find the most recent
        ancestor of HEAD that occurs on a tracking branch.

        Returns:
            git.Commit object or None
        """
        possible_relatives = []
        try:
            if not self.repo:
                return None
            try:
                active_branch = self.repo.active_branch
            except (TypeError, ValueError):
                logger.debug("git is in a detached head state")
                return None  # detached head
            else:
                tracking_branch = active_branch.tracking_branch()
                if tracking_branch:
                    possible_relatives.append(tracking_branch.commit)

            if not possible_relatives:
                for branch in self.repo.branches:  # type: ignore[attr-defined]
                    tracking_branch = branch.tracking_branch()
                    if tracking_branch is not None:
                        possible_relatives.append(tracking_branch.commit)

            head = self.repo.head
            most_recent_ancestor = None
            for possible_relative in possible_relatives:
                # at most one:
                for ancestor in self.repo.merge_base(head, possible_relative):
                    if most_recent_ancestor is None:
                        most_recent_ancestor = ancestor
                    elif self.repo.is_ancestor(most_recent_ancestor, ancestor):  # type: ignore
                        most_recent_ancestor = ancestor
            return most_recent_ancestor
        except GitCommandError as e:
            logger.debug("git remote upstream fork point could not be found")
            logger.debug(str(e))
            return None

    def tag(self, name: str, message: Optional[str]) -> Any:
        if not self.repo:
            return None
        try:
            return self.repo.create_tag(f"wandb/{name}", message=message, force=True)
        except GitCommandError:
            print("Failed to tag repository.")
            return None

    def push(self, name: str) -> Any:
        if not self.remote:
            return None
        try:
            return self.remote.push(f"wandb/{name}", force=True)
        except GitCommandError:
            logger.debug("failed to push git")
            return None
