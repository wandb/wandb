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

# Transports that let a remote URL execute an arbitrary command or read
# arbitrary local files. These are never legitimate for a launch job's source
# repository, and a remote is attacker-controlled data (it is read back from a
# job artifact and replayed to every agent that pops the queue). Reject them
# before any git process sees the URL.
_DISALLOWED_URI_PREFIXES = ("ext::", "fd::", "file://")

# Force git to refuse the local-file and ext transports for the fetches it
# performs, including the recursive submodule fetches. This closes the
# malicious-submodule RCE class (e.g. CVE-2024-32002) even on host git binaries
# that predate the upstream default of protocol.file.allow=user, and blocks the
# ext:: command transport as defense in depth if the prefix check above is ever
# bypassed. `submodule update --recursive` is passed explicitly, so
# `submodule.recurse=false` would not help here; the protocol allowlist is what
# gates the dangerous transports.
_FETCH_PROTOCOL_ARGS = ("-c", "protocol.ext.allow=never")
_SUBMODULE_PROTOCOL_ARGS = (
    "-c",
    "protocol.file.allow=never",
    "-c",
    "protocol.ext.allow=never",
)


def _validate_uri(uri: str) -> None:
    """Reject remote URLs that git would treat as a command or an option.

    Raises:
        LaunchError: If the URI uses a command-executing transport or looks
            like a command-line option (argument injection).
    """
    stripped = uri.strip()
    if stripped.startswith("-"):
        raise LaunchError(
            f"Refusing to fetch git remote that looks like a command-line "
            f"option: {uri!r}"
        )
    lowered = stripped.lower()
    for prefix in _DISALLOWED_URI_PREFIXES:
        if lowered.startswith(prefix):
            raise LaunchError(
                f"Refusing to fetch git remote using a disallowed transport "
                f"({prefix!r}): {uri!r}"
            )


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
        _validate_uri(self.uri)
        try:
            run_git("init", dst_dir)
            self.path = os.path.abspath(dst_dir)
            run_git("remote", "add", "origin", "--", self.uri, cwd=dst_dir)
            # We fetch the origin so that we have branch and tag references
            run_git(*_FETCH_PROTOCOL_ARGS, "fetch", "origin", cwd=dst_dir)
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
        try:
            run_git(
                *_SUBMODULE_PROTOCOL_ARGS,
                "submodule",
                "update",
                "--init",
                "--recursive",
                cwd=dst_dir,
            )
        except GitCommandError as e:
            raise LaunchError(
                f"Unable to update submodules for git repository {self.url}:\n{e}"
            )

    def _ref_exists(self, dst_dir: str, ref: str) -> bool:
        try:
            run_git("show-ref", "--verify", "--quiet", ref, cwd=dst_dir)
        except GitCommandError:
            return False
        else:
            return True

    def _checkout_branch(self, dst_dir: str, branch: str, ref: str) -> None:
        run_git("checkout", "-B", branch, ref, cwd=dst_dir)
