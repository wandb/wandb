"""Support for parsing GitHub URLs (which might be user provided) into constituent parts."""

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple, Union

from wandb.sdk.launch.errors import LaunchError

PREFIX_HTTPS = "https://"
PREFIX_SSH = "git@"
SUFFIX_GIT = ".git"


GIT_COMMIT_REGEX = re.compile(r"[0-9a-f]{40}")


class ReferenceType(IntEnum):
    BRANCH = 1
    COMMIT = 2


def _parse_netloc(netloc: str) -> Tuple[Optional[str], Optional[str], str]:
    """Parse netloc into username, password, and host.

    github.com => None, None, "@github.com"
    username@github.com => "username", None, "github.com"
    username:password@github.com => "username", "password", "github.com"
    """
    parts = netloc.split("@", 1)
    if len(parts) == 1:
        return None, None, parts[0]
    auth, host = parts
    parts = auth.split(":", 1)
    if len(parts) == 1:
        return parts[0], None, host
    return parts[0], parts[1], host


@dataclass
class GitReference:
    def __init__(self, remote: str, ref: Optional[str] = None) -> None:
        """Initialize a reference from a remote and ref.

        Arguments:
            remote: A remote URL or URI.
            ref: A branch, tag, or commit hash.
        """
        self.uri = remote
        self.ref = ref

    @property
    def url(self) -> Optional[str]:
        return self.uri

    def fetch(self, dst_dir: str) -> None:
        """Fetch the repo into dst_dir and refine githubref based on what we learn."""
        # We defer importing git until the last moment, because the import requires that the git
        # executable is available on the PATH, so we only want to fail if we actually need it.
        import git  # type: ignore

        repo = git.Repo.init(dst_dir)
        self.path = repo.working_dir
        origin = repo.create_remote("origin", self.uri or "")

        try:
            # We fetch the origin so that we have branch and tag references
            origin.fetch()
        except git.exc.GitCommandError as e:
            raise LaunchError(
                f"Unable to fetch from git remote repository {self.url}:\n{e}"
            )

        ref: Union[git.RemoteReference, str]
        if self.ref:
            if self.ref in origin.refs:
                ref = origin.refs[self.ref]
            else:
                ref = self.ref
            head = repo.create_head(self.ref, ref)
            head.checkout()
            self.commit_hash = head.commit.hexsha

        else:
            # TODO: Is there a better way to do this?
            default_branch = None
            for ref in repo.references:
                if hasattr(ref, "tag"):  # Skip tag references
                    continue
                refname = ref.name
                if refname.startswith("origin/"):  # Trim off "origin/"
                    refname = refname[7:]
                if refname == "main":
                    default_branch = "main"
                    break
                if refname == "master":
                    default_branch = "master"
                    # Keep looking in case we also have a main, which we let take precedence
                    # (While the references appear to be sorted, not clear if that's guaranteed.)
            if not default_branch:
                raise LaunchError(
                    f"Unable to determine branch or commit to checkout from {self.url}"
                )
            self.default_branch = default_branch
            self.ref = default_branch
            head = repo.create_head(default_branch, origin.refs[default_branch])
            head.checkout()
            self.commit_hash = head.commit.hexsha
        repo.submodule_update(init=True, recursive=True)
