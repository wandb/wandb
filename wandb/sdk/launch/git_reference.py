"""Support for parsing GitHub URLs (which might be user provided) into constituent parts."""

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple

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

        repo = git.Repo.clone_from(self.uri, dst_dir, depth=1)
        self.path = repo.working_dir
        refspec = f"{self.ref}:{self.ref}" if self.ref else None
        repo.git.fetch(self.uri, refspec)
        if self.ref:
            repo.git.checkout(self.ref)
        repo.submodule_update(init=True, recursive=True)
        self.commit_hash = repo.head.commit.hexsha
