import logging
import os

from six.moves import configparser
from six.moves.urllib.parse import urlparse

import wandb.core

logger = logging.getLogger(__name__)


class GitRepo(object):
    def __init__(self, root=None, remote="origin", lazy=True):
        self.remote_name = remote
        self._root = root
        self._repo = None
        if not lazy:
            self.repo

    @property
    def repo(self):
        if self._repo is None:
            if self.remote_name is None:
                self._repo = False
            else:
                try:
                    self._repo = Repo(self._root or os.getcwd(),
                                      search_parent_directories=True)
                except exc.InvalidGitRepositoryError:
                    logger.debug("git repository is invalid")
                    self._repo = False
        return self._repo

    def is_untracked(self, file_name):
        if not self.repo:
            return True
        return file_name in self.repo.untracked_files

    @property
    def enabled(self):
        return bool(self.repo)

    @property
    def root(self):
        if not self.repo:
            return False
        return self.repo.git.rev_parse("--show-toplevel")

    @property
    def dirty(self):
        if not self.repo:
            return False
        return self.repo.is_dirty()

    @property
    def email(self):
        if not self.repo:
            return None
        try:
            return self.repo.config_reader().get_value("user", "email")
        except configparser.Error:
            return None

    @property
    def last_commit(self):
        if not self.repo:
            return None
        if not self.repo.head or not self.repo.head.is_valid():
            return None
        if len(self.repo.refs) > 0:
            return self.repo.head.commit.hexsha
        else:
            return self.repo.git.show_ref("--head").split(" ")[0]

    @property
    def branch(self):
        if not self.repo:
            return None
        return self.repo.head.ref.name

    @property
    def remote(self):
        if not self.repo:
            return None
        try:
            return self.repo.remotes[self.remote_name]
        except IndexError:
            return None

    # the --submodule=diff option doesn't exist in pre-2.11 versions of git (november 2016)
    # https://stackoverflow.com/questions/10757091/git-list-of-all-changed-files-including-those-in-submodules
    @property
    def has_submodule_diff(self):
        if not self.repo:
            return False
        return self.repo.git.version_info >= (2, 11, 0)

    @property
    def remote_url(self):
        if not self.remote:
            return None
        return self.remote.url

    @property
    def root_dir(self):
        if not self.repo:
            return None
        return self.repo.git.rev_parse("--show-toplevel")

    def get_upstream_fork_point(self):
        """Get the most recent ancestor of HEAD that occurs on an upstream
        branch.

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
                for branch in self.repo.branches:
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
                    elif self.repo.is_ancestor(most_recent_ancestor, ancestor):
                        most_recent_ancestor = ancestor
            return most_recent_ancestor
        except exc.GitCommandError as e:
            logger.debug("git remote upstream fork point could not be found")
            logger.debug(e.message)
            return None

    def tag(self, name, message):
        try:
            return self.repo.create_tag("wandb/" + name, message=message, force=True)
        except exc.GitCommandError:
            print("Failed to tag repository.")
            return None

    def push(self, name):
        if self.remote:
            try:
                return self.remote.push("wandb/" + name, force=True)
            except exc.GitCommandError:
                logger.debug("failed to push git")
                return None


class FakeGitRepo(GitRepo):
    @property
    def repo(self):
        return None


try:
    from git import Repo, exc
except ImportError:  # import fails if user doesn't have git
    GitRepo = FakeGitRepo
