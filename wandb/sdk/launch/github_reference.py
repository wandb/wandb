"""Support for parsing GitHub URLs (which might be user provided) into constituent parts."""

import os
import re
import tempfile
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple
from urllib.parse import urlparse

from wandb.sdk.launch.errors import LaunchError

if TYPE_CHECKING:
    # We defer importing git until the last moment, because the import requires that the git
    # executable is available on the PATH, so we only want to fail if we actually need it.
    import git  # type: ignore


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
class GitHubReference:
    username: Optional[str] = None
    password: Optional[str] = None
    host: Optional[str] = None

    organization: Optional[str] = None
    repo: Optional[str] = None

    view: Optional[str] = None  # tree or blob

    # Set when we don't know how to parse yet
    path: Optional[str] = None

    # Set when we do know
    default_branch: Optional[str] = None

    ref: Optional[str] = None  # branch or commit
    ref_type: Optional[ReferenceType] = None
    commit_hash: Optional[str] = None  # hash of commit

    directory: Optional[str] = None
    file: Optional[str] = None

    # Location of repo locally if pulled
    local_dir: Optional[tempfile.TemporaryDirectory] = None

    repo_object: Optional["git.Repo"] = None

    def __del__(self) -> None:
        # on delete, clean up the local directory
        if self.local_dir:
            self.local_dir.cleanup()

    def update_ref(self, ref: Optional[str]) -> None:
        if ref:
            # We no longer know what this refers to
            self.ref_type = None
            self.ref = ref

    @property
    def url_host(self) -> str:
        assert self.host
        auth = self.username or ""
        if self.password:
            auth += f":{self.password}"
        if auth:
            auth += "@"
        return f"{PREFIX_HTTPS}{auth}{self.host}"

    @property
    def url_organization(self) -> str:
        assert self.organization
        return f"{self.url_host}/{self.organization}"

    @property
    def url_repo(self) -> str:
        assert self.repo
        return f"{self.url_organization}/{self.repo}"

    @property
    def repo_ssh(self) -> str:
        return f"{PREFIX_SSH}{self.host}:{self.organization}/{self.repo}{SUFFIX_GIT}"

    @property
    def url(self) -> str:
        url = self.url_repo
        if self.view:
            url += f"/{self.view}"
        if self.ref:
            url += f"/{self.ref}"
            if self.directory:
                url += f"/{self.directory}"
            if self.file:
                url += f"/{self.file}"
        if self.path:
            url += f"/{self.path}"
        return url

    @staticmethod
    def parse(uri: str) -> Optional["GitHubReference"]:
        """Attempt to parse a string as a GitHub URL."""
        # Special case: git@github.com:wandb/wandb.git
        ref = GitHubReference()
        if uri.startswith(PREFIX_SSH):
            index = uri.find(":", len(PREFIX_SSH))
            if index > 0:
                ref.host = uri[len(PREFIX_SSH) : index]
                parts = uri[index + 1 :].split("/", 1)
                if len(parts) < 2 or not parts[1].endswith(SUFFIX_GIT):
                    return None
                ref.organization = parts[0]
                ref.repo = parts[1][: -len(SUFFIX_GIT)]
                return ref
            else:
                # Could not parse host name
                return None

        parsed = urlparse(uri)
        if parsed.scheme != "https":
            return None
        ref.username, ref.password, ref.host = _parse_netloc(parsed.netloc)

        parts = parsed.path.split("/")
        if len(parts) < 2:
            return ref
        if parts[1] == "orgs" and len(parts) > 2:
            ref.organization = parts[2]
            return ref
        ref.organization = parts[1]
        if len(parts) < 3:
            return ref
        repo = parts[2]
        if repo.endswith(SUFFIX_GIT):
            repo = repo[: -len(SUFFIX_GIT)]
        ref.repo = repo
        ref.view = parts[3] if len(parts) > 3 else None
        ref.path = "/".join(parts[4:])

        return ref

    def fetch(self, dst_dir: str) -> None:
        """Fetch the repo into dst_dir and refine githubref based on what we learn."""
        import git

        repo = git.Repo.init(dst_dir)
        try:
            origin = repo.create_remote("origin", self.url_repo)
        except git.exc.GitCommandError:
            # Origin already exists
            origin = repo.remote("origin")

        # We fetch the origin so that we have branch and tag references
        origin.fetch(depth=1)

        # Guess if this is a commit
        commit = None
        first_segment = self.ref or (self.path.split("/")[0] if self.path else "")
        if GIT_COMMIT_REGEX.fullmatch(first_segment):
            try:
                commit = repo.commit(first_segment)
                self.ref_type = ReferenceType.COMMIT
                self.ref = first_segment
                if self.path:
                    self.path = self.path[len(first_segment) + 1 :]
                head = repo.create_head(first_segment, commit)
                head.checkout()
                self.commit_hash = head.commit.hexsha
            except ValueError:
                # Apparently it just looked like a commit
                pass

        # If not a commit, check to see if path indicates a branch name
        branch = None
        check_branch = self.ref or self.path
        if not commit and check_branch:
            for ref in repo.references:
                if hasattr(ref, "tag"):
                    # Skip tag references.
                    # Using hasattr instead of isinstance because it works better with mocks.
                    continue
                refname = ref.name
                if refname.startswith("origin/"):  # Trim off "origin/"
                    refname = refname[7:]
                if check_branch.startswith(refname):
                    self.ref_type = ReferenceType.BRANCH
                    self.ref = branch = refname
                    if self.path:
                        self.path = self.path[len(refname) + 1 :]
                    head = repo.create_head(branch, origin.refs[branch])
                    head.checkout()
                    self.commit_hash = head.commit.hexsha
                    break

        # Must be on default branch. Try to figure out what that is.
        # TODO: Is there a better way to do this?
        default_branch = None
        if not commit and not branch:
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
            head = repo.create_head(default_branch, origin.refs[default_branch])
            head.checkout()
            self.commit_hash = head.commit.hexsha
        repo.submodule_update(init=True, recursive=True)

        # Now that we've checked something out, try to extract directory and file from what remains
        self._update_path(dst_dir)

    def _update_path(self, dst_dir: str) -> None:
        """Set directory and file fields based on what remains in path."""
        if not self.path:
            return
        path = Path(dst_dir, self.path)
        if path.is_file():
            self.directory = str(path.parent.absolute())
            self.file = path.name
            self.path = None
        elif path.is_dir():
            self.directory = self.path
            self.path = None

    def _clone_repo(self) -> None:
        """Clone the repo to a temp directory."""
        if self.local_dir is not None:
            # Repo already cloned, location is stored in self.local_dir.name
            return
        import git

        dst_dir = tempfile.TemporaryDirectory()
        self.repo_object = git.Repo.clone_from(self.repo_ssh, dst_dir.name, depth=1)
        self.local_dir = dst_dir

        if not self.repo_object:
            self.local_dir.cleanup()
            raise LaunchError(f"Error cloning git repo: {self.repo_ssh}")

    def get_commit(self) -> str:
        """Get git hash associated with the reference."""
        self._clone_repo()
        assert self.repo_object, "Repo object not properly initialized"
        return self.repo_object.head.commit.hexsha  # type: ignore

    def get_file(self, local_path: str) -> Optional[str]:
        """Pull a file from the repo.

        :local_path: relative path to the file in the repo

        :return: tmpdir local path to the file if it exists, None otherwise
        """
        self._clone_repo()
        assert (
            self.local_dir is not None
        )  # Always true, but stops mypy from complaining
        file = os.path.join(self.local_dir.name, local_path)
        return file if os.path.isfile(file) else None
