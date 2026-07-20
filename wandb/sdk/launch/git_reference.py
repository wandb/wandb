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

# Launch jobs specify their source as a git remote. Restrict that remote to the
# transports a git repository is served over -- https://, ssh://, and the
# scp-like git@host:path form -- via a positive allowlist. Other values
# (file://, ext::, fd::, git://, http://, bare local paths, and values that git
# would read as a command-line option) are rejected before the remote is handed
# to git.
_SCP_LIKE_REMOTE = re.compile(r"^[\w.+-]+@[\w.-]+:.+", re.ASCII)

# Pin git's protocol allowlist on every fetch, including the recursive submodule
# fetches, so only the intended transports are used -- including for submodule
# URLs declared in .gitmodules -- even on host git that predates the upstream
# protocol.file.allow=user default. `submodule update --recursive` is passed
# explicitly, so `submodule.recurse=false` would not apply here; the
# protocol.*.allow settings are what constrain the transports.
_PROTOCOL_HARDENING = (
    "-c",
    "protocol.file.allow=never",
    "-c",
    "protocol.ext.allow=never",
)


def _validate_uri(uri: str) -> None:
    """Restrict a git remote to the supported transports.

    Only ``https://``, ``ssh://``, and scp-like ``git@host:path`` remotes are
    permitted.

    Raises:
        LaunchError: If the remote is not one of the supported transports.
    """
    stripped = uri.strip()
    # A leading "-" would be read by git as a command-line flag, and can also
    # slip past the scp-like check below, so reject it explicitly.
    if stripped.startswith("-"):
        raise LaunchError(
            f"Refusing to fetch git remote {uri!r}: only https://, ssh://, and "
            f"git@host:path remotes are allowed."
        )
    if stripped.lower().startswith((PREFIX_HTTPS, "ssh://")) or _SCP_LIKE_REMOTE.match(
        stripped
    ):
        return
    raise LaunchError(
        f"Refusing to fetch git remote {uri!r}: only https://, ssh://, and "
        f"git@host:path remotes are allowed."
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
            run_git(*_PROTOCOL_HARDENING, "fetch", "origin", cwd=dst_dir)
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
                *_PROTOCOL_HARDENING,
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
