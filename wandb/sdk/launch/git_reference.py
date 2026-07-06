"""Support for parsing GitHub URLs (which might be user provided) into constituent parts."""

from __future__ import annotations

import os
import re
from enum import IntEnum

from wandb.sdk.launch.errors import LaunchError
from wandb.sdk.lib.gitlib import GitCommandError, run_git

PREFIX_HTTPS = "https://"
PREFIX_SSH = "git@"
SUFFIX_GIT = ".git"


GIT_COMMIT_REGEX = re.compile(r"[0-9a-f]{40}")


class ReferenceType(IntEnum):
    BRANCH = 1
    COMMIT = 2


class GitReference:
    def __init__(self, remote: str, ref: str | None = None) -> None:
        """Initialize a reference from a remote and ref.

        Arguments:
            remote: A remote URL or URI.
            ref: A branch, tag, or commit hash.
        """
        self.uri = remote
        self.ref = ref
        self.path: str | None = None
        self.commit_hash: str | None = None
        self.default_branch: str | None = None

    @property
    def url(self) -> str | None:
        return self.uri

    def fetch(self, dst_dir: str) -> None:
        """Fetch the repo into dst_dir and refine githubref based on what we learn."""
        try:
            run_git("init", dst_dir)
            self.path = os.path.abspath(dst_dir)
            run_git("remote", "add", "origin", self.uri, cwd=dst_dir)
            # We fetch the origin so that we have branch and tag references
            run_git("fetch", "origin", cwd=dst_dir)
        except GitCommandError as e:
            raise LaunchError(
                f"Unable to fetch from git remote repository {self.url}:\n{e}"
            )

        if self.ref:
            if self._ref_exists(dst_dir, f"refs/remotes/origin/{self.ref}"):
                ref = f"origin/{self.ref}"
            else:
                ref = self.ref
            self._checkout_branch(dst_dir, self.ref, ref)
        else:
            default_branch = None
            for branch in ("main", "master"):
                if self._ref_exists(dst_dir, f"refs/remotes/origin/{branch}"):
                    default_branch = branch
                    break
            if not default_branch:
                raise LaunchError(
                    f"Unable to determine branch or commit to checkout from {self.url}"
                )
            self.default_branch = default_branch
            self.ref = default_branch
            self._checkout_branch(dst_dir, default_branch, f"origin/{default_branch}")

        self.commit_hash = run_git("rev-parse", "HEAD", cwd=dst_dir).strip()
        run_git("submodule", "update", "--init", "--recursive", cwd=dst_dir)

    def _ref_exists(self, dst_dir: str, ref: str) -> bool:
        try:
            run_git("show-ref", "--verify", "--quiet", ref, cwd=dst_dir)
        except GitCommandError:
            return False
        else:
            return True

    def _checkout_branch(self, dst_dir: str, branch: str, ref: str) -> None:
        run_git("checkout", "-B", branch, ref, cwd=dst_dir)
