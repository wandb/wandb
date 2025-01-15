from __future__ import annotations

import json
import secrets
import subprocess
import sys
from collections import deque
from dataclasses import InitVar, asdict, dataclass, field
from pathlib import Path
from string import ascii_lowercase, digits
from typing import Any, ClassVar, Final, Generator, Literal

import httpx
import pytest

if sys.version_info < (3, 12):
    from typing_extensions import dataclass_transform
else:
    from typing import dataclass_transform


#: The root directory of this repo.
REPO_ROOT: Final[Path] = Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class LocalWandbBackendAddress:
    host: str
    base_port: int
    fixture_port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.base_port}"

    @property
    def fixture_service_url(self) -> str:
        return f"http://{self.host}:{self.fixture_port}"


@pytest.fixture(scope="session")
def local_wandb_backend() -> LocalWandbBackendAddress:
    """Fixture that starts up or connects to the local-testcontainer.

    This does not patch WANDB_BASE_URL! Use `use_local_wandb_backend` instead.
    """
    return _local_wandb_backend(name="wandb-local-testcontainer")


@pytest.fixture(scope="session")
def local_wandb_backend_importers() -> LocalWandbBackendAddress:
    """Fixture that starts up or connects to a second local-testcontainer.

    This is used by importer tests, to move data between two backends.
    """
    return _local_wandb_backend(name="wandb-local-testcontainer-importers")


def _local_wandb_backend(name: str) -> LocalWandbBackendAddress:
    tool_file = REPO_ROOT / "tools" / "local_wandb_server.py"

    result = subprocess.run(
        [
            "python",
            tool_file,
            "connect",
            f"--name={name}",
        ],
        stdout=subprocess.PIPE,
    )

    if result.returncode != 0:
        raise AssertionError(
            "`python tools/local_wandb_server.py connect` failed. See stderr."
            " Did you run `python tools/local_wandb_server.py start`?"
        )

    output = json.loads(result.stdout)
    address = LocalWandbBackendAddress(
        host="localhost",
        base_port=int(output["base_port"]),
        fixture_port=int(output["fixture_port"]),
    )
    return address


@pytest.fixture(scope="session")
def use_local_wandb_backend(
    local_wandb_backend: LocalWandbBackendAddress,
) -> Generator[None, None, None]:
    """Fixture that patches WANDB_BASE_URL to point to the local container.

    We use the `pytest.MonkeyPatch` context manager instead of the `monkeypatch` fixture,
    as `monkeypatch` is strictly function-scoped and we need this to be session-scoped.
    """
    with pytest.MonkeyPatch.context() as session_monkeypatch:
        session_monkeypatch.setenv("WANDB_BASE_URL", local_wandb_backend.base_url)
        yield


@dataclass(frozen=True)
@dataclass_transform(frozen_default=True)
class FixtureCmd:
    path: ClassVar[str]  # e.g. "db/user"

    command: str


@dataclass(frozen=True)
class UserCmd(FixtureCmd):
    path: ClassVar[str] = "db/user"

    command: Literal["up", "down", "down_all", "logout", "login", "password"]

    username: str | None = None
    password: str | None = None
    admin: bool = False


@dataclass(frozen=True)
class OrgCmd(FixtureCmd):
    path: ClassVar[str] = "db/organization"

    command: Literal["up", "down", "add_members"]

    orgName: str  # noqa: N815
    username: str | None = None
    fixtureData: OrgState | None = None  # noqa: N815


@dataclass(frozen=True)
class OrgState:
    members: list[OrgMemberState]


@dataclass(frozen=True)
class OrgMemberState:
    username: str
    role: Literal["admin", "member", "viewer"]


def random_string(alphabet: str = ascii_lowercase + digits, length: int = 12) -> str:
    """Generate a random string of a given length.

    Args:
        alphabet: A sequence of allowed characters in the generated string.
        length: Length of the string to generate.

    Returns:
        A random string.
    """
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class BackendFixtureFactory:
    service_url: InitVar[str]  #: Local base URL for backend fixture service.

    worker_id: str  #: Identifies the current worker in pytest-xdist parallel runs.

    _client: httpx.Client = field(init=False)
    _cleanup_stack: deque[FixtureCmd] = field(default_factory=deque, init=False)

    def __post_init__(self, service_url: str):
        self._client = httpx.Client(
            base_url=service_url,
            # event_hooks={"response": [httpx.Response.raise_for_status]},
            # timeout=None,
        )

    def __enter__(self):
        self._client.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        self._client.__exit__()

    def make_user(self, name: str | None = None, admin: bool = False) -> str:
        """Create a new user and return their username."""
        name = name or f"user-{self.worker_id}-{random_string()}"

        self.send_cmds(
            UserCmd("up", username=name, admin=admin),
            UserCmd("password", username=name, password=name, admin=admin),
        )

        # Register command(s) to delete the user on cleanup
        self._cleanup_stack.append(
            UserCmd("down", username=name, admin=admin),
        )
        return name

    def make_org(self, name: str | None = None, *, username: str) -> str:
        """Create a new org with the username as a member and return the org name."""
        name = name or f"org-{self.worker_id}-{random_string()}"
        self.send_cmds(
            OrgCmd("up", orgName=name, username=username),
        )
        # Register command(s) to delete the org on cleanup
        self._cleanup_stack.append(
            OrgCmd("down", orgName=name),
        )
        return name

    def send_cmds(self, *cmds: FixtureCmd) -> None:
        for cmd in cmds:
            self._send(cmd.path, data=asdict(cmd))

    def _send(self, path: str, data: dict[str, Any]) -> None:
        # trigger fixture
        endpoint = str(self._client.base_url.join(path))
        # FIXME: Figure out how SDK team preferences/conventions for replacing print statements
        print(f"Triggering fixture on {endpoint!r}: {data!r}", file=sys.stderr)  # noqa: T201
        try:
            response = self._client.post(path, json=data)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # FIXME: Figure out how SDK team preferences/conventions for replacing print statements
            print(e.response.json(), file=sys.stderr)  # noqa: T201

    def cleanup(self) -> None:
        while True:
            try:
                cmd = self._cleanup_stack.pop()
            except IndexError:
                break
            else:
                self._send(cmd.path, data=asdict(cmd))


@pytest.fixture(scope="session")
def backend_fixture_factory(
    worker_id: str,
    local_wandb_backend: LocalWandbBackendAddress,
    use_local_wandb_backend: None,
) -> Generator[BackendFixtureFactory, None, None]:
    base_url = local_wandb_backend.fixture_service_url
    with BackendFixtureFactory(base_url, worker_id=worker_id) as factory:
        yield factory


@pytest.fixture(scope="session")
def backend_importers_fixture_factory(
    worker_id: str,
    local_wandb_backend_importers: LocalWandbBackendAddress,
) -> Generator[BackendFixtureFactory, None, None]:
    base_url = local_wandb_backend_importers.fixture_service_url
    with BackendFixtureFactory(base_url, worker_id=worker_id) as factory:
        yield factory
