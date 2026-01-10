"""Commands for using a local-testcontainer for testing."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import pathlib
import pprint
import re
import shlex
import subprocess
import sys
import time
import traceback
from collections.abc import Iterator

import click
import filelock
import pydantic
import requests


@click.group()
def main():
    """Start or stop a W&B backend for testing.

    This manages a singleton local-testcontainer Docker process on your system.
    You must start it up manually before running system_tests by using the
    start command. You can then stop it by using the stop command.
    """


@main.command()
@click.option(
    "--name",
    help="The name for the server. This is used by 'connect' in pytest.",
    default="wandb-local-testcontainer",
)
@click.option(
    "--hostname",
    help="""The hostname for a running backend (e.g. localhost).
    If provided, then --base-port and --fixture-port are required.
    """,
)
@click.option(
    "--base-port",
    help="The backend's 'base' port (usually 8080).",
    type=int,
)
@click.option(
    "--fixture-port",
    help="The backend's 'fixture' port (usually 9015)",
    type=int,
)
def start(
    name: str,
    hostname: str | None,
    base_port: int | None,
    fixture_port: int | None,
) -> None:
    """Start a local-testcontainer.

    By default, starts an interactive session for spinning up the right
    Docker container. If --hostname, --base-port and --fixture-port are
    provided, then non-interactively connects to an existing container.
    """
    if not hostname:
        _start_interactively(name=name)

    else:
        if not base_port:
            raise AssertionError("--base-port required")
        if not fixture_port:
            raise AssertionError("--fixture-port required")

        _start_external(
            name=name,
            hostname=hostname,
            base_port=base_port,
            fixture_port=fixture_port,
        )


@main.command()
@click.option(
    "--name",
    help="The name used in the 'start' command.",
    default="wandb-local-testcontainer",
)
def connect(name: str) -> None:
    """Connect to a running local-testcontainer.

    The exit code is 0 if there is a known local-testcontainer and it's healthy.
    Otherwise, the exit code is 1.

    On success, prints a JSON dictionary with the following keys:

        base_port: The main port (for GraphQL / FileStream / web UI)
        fixture_port: Port used for test-specific functionalities
    """
    with _info_file() as info:
        server = info.servers.get(name)

    if not server:
        _echo_bad(
            f"Server {name} is not running. To start it, run:\n"
            f"\tpython tools/local_wandb_server.py start --name={name}"
        )
        sys.exit(1)

    health_url = f"http://{server.hostname}:{server.base_port}/healthz"
    if not _check_health(health_url):
        _echo_bad(f"{health_url} did not respond HTTP 200.")
        sys.exit(1)

    _echo_good(f"Server {name} is healthy.")

    click.echo(
        json.dumps(
            {
                "base_port": server.base_port,
                "fixture_port": server.fixture_port,
            }
        )
    )


def _start_interactively(name: str) -> None:
    with _info_file() as info:
        if prev := info.servers.get(name):
            app_health_url = f"http://{prev.hostname}:{prev.base_port}/healthz"
            fixture_health_url = f"http://{prev.hostname}:{prev.fixture_port}/health"

            if _check_health(app_health_url) and _check_health(fixture_health_url):
                _echo_bad(f"Server {name!r} is already running and healthy.")
                sys.exit(1)

            _echo_info(f"Server {name!r} is no longer running or healthy.  Restarting.")

        server = _ServerInfo(
            managed=True,
            hostname="localhost",
            base_port=0,
            fixture_port=0,
        )
        info.servers[name] = server

        _start_container(name=name).apply_ports(server)

        if not _check_health(
            f"http://{server.hostname}:{server.base_port}/healthz",
            timeout=30,
        ):
            _echo_bad(f"Server {name!r} did not become healthy in time (base).")
            sys.exit(1)

        if not _check_health(
            f"http://{server.hostname}:{server.fixture_port}/health",
            timeout=30,
        ):
            _echo_bad(f"Server {name!r} did not become healthy in time (fixtures).")
            sys.exit(1)

        _echo_good(f"Server {name!r} is up and healthy!")


def _start_external(
    name: str,
    hostname: str,
    base_port: int,
    fixture_port: int,
) -> None:
    with _info_file() as info:
        if name in info.servers:
            _echo_bad(f"Server {name} is already running.")
            sys.exit(1)

        info.servers[name] = _ServerInfo(
            managed=False,
            hostname=hostname,
            base_port=base_port,
            fixture_port=fixture_port,
        )

        app_health_url = f"http://{hostname}:{base_port}/healthz"
        fixture_health_url = f"http://{hostname}:{fixture_port}/health"  # no z

        if not _check_health(app_health_url, timeout=30):
            _echo_bad(f"{app_health_url} did not respond HTTP 200.")
            sys.exit(1)

        if not _check_health(fixture_health_url, timeout=30):
            _echo_bad(f"{fixture_health_url} did not respond HTTP 200.")
            sys.exit(1)

        _echo_good("Server is healthy!")


@main.command()
@click.option(
    "--name",
    "names",
    help="A name passed to 'start'. If not provided, stops all servers.",
    default=[],
    multiple=True,
)
def stop(names: list[str]) -> None:
    """Stops containers started by this script."""
    all_good = True

    with _info_file() as info:
        if not names:
            names = list(info.servers.keys())

        if not names:
            _echo_bad("No servers to stop.")
            sys.exit(1)

        for name in names:
            server = info.servers.pop(name, None)
            if not server:
                _echo_bad(f"No server called {name}.")
                all_good = False
                continue

            if not server.managed:
                _echo_info(
                    f"Forgetting {name}, but not stopping it because"
                    " it wasn't started by this script."
                )
                continue

            try:
                _stop_container(name)
                _echo_info(f"Shut down {name}.")
            except Exception as e:
                traceback.print_exception(e, file=sys.stderr)
                _echo_bad(f"Failed to stop {name}; forgetting it anyway.")
                all_good = False

    if not all_good:
        sys.exit(1)


@main.command(name="print-debug")
def print_debug() -> None:
    """Dump information for debugging this script."""
    with _info_file() as info:
        _echo_info(pprint.pformat(info))


def _resources(suffix: str) -> pathlib.Path:
    return pathlib.Path(__file__).with_suffix(suffix)


@contextlib.contextmanager
def _info_file() -> Iterator[_InfoFile]:
    with filelock.FileLock(_resources(".state.lock")):
        with open(_resources(".state"), "a+") as f:
            f.seek(0)
            content = f.read()

            if content:
                try:
                    state = _InfoFile.model_validate_json(content)
                except Exception as e:
                    _echo_bad(f"Couldn't parse state file; remaking it: {e}")
                    state = _InfoFile()
            else:
                state = _InfoFile()

            yield state

            f.truncate(0)
            f.write(state.model_dump_json())


class _InfoFile(pydantic.BaseModel):
    servers: dict[str, _ServerInfo] = {}
    """Map from server names to information about them."""


class _ServerInfo(pydantic.BaseModel):
    managed: bool
    """Whether this script started the server or just connected to it."""

    hostname: str
    """The server's address, e.g. 'localhost'."""

    base_port: int
    """The exposed 'base' port, used for GraphQL and FileStream APIs."""

    fixture_port: int
    """The exposed 'fixture' port, used for test-related functionalities."""


def _check_health(health_url: str, timeout: int = 1) -> bool:
    """Returns True if the URL responds with HTTP 200 within a timeout.

    Args:
        health_url: The URL to which to make GET requests.
        timeout: The timeout in seconds after which to give up.
    """
    start_time = time.monotonic()

    _echo_info(
        f"Waiting up to {timeout} second(s) until {health_url} responds with HTTP 200."
    )

    while True:
        try:
            response = requests.get(health_url)
            if response.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass

        if time.monotonic() - start_time >= timeout:
            return False

        time.sleep(1)


@dataclasses.dataclass(frozen=True)
class _WandbContainerPorts:
    base_port: int
    fixture_port: int

    def apply_ports(self, server: _ServerInfo) -> None:
        server.base_port = self.base_port
        server.fixture_port = self.fixture_port


def _start_container(*, name: str) -> _WandbContainerPorts:
    """Start the local-testcontainer.

    This issues the `docker run` command and returns immediately.

    Args:
        name: The container name to use.
    """
    registry = click.prompt("Registry", default="us-central1-docker.pkg.dev")
    repository = click.prompt(
        "Repository", default="wandb-production/images/local-testcontainer"
    )
    tag = click.prompt("Tag", default="master")
    pull = click.prompt(
        "--pull",
        default="always",
        type=click.Choice(["always", "never", "missing"]),
    )

    docker_flags = [
        "--rm",
        "--detach",
        *["--pull", pull],
        *["-e", "WANDB_ENABLE_TEST_CONTAINER=true"],
        *["--name", name],
        *["--volume", f"{name}-vol:/vol"],
        # Expose ports to the host.
        *["--publish", "8080"],  # base port
        *["--publish", "9015"],  # fixture port
        # Only this platform is available for now. Without specifying it,
        # Docker defaults to the host's platform and fails if it's not
        # supported.
        *["--platform", "linux/amd64"],
    ]

    image = f"{registry}/{repository}:{tag}"
    command = ["docker", "run", *docker_flags, image]

    _echo_info(f"Running command: {shlex.join(command)}")
    subprocess.check_call(command, stdout=sys.stderr)
    return _get_ports_retrying(name)


def _stop_container(name: str) -> None:
    subprocess.check_call(["docker", "rm", "-f", name], stdout=sys.stderr)


def _get_ports_retrying(name: str) -> _WandbContainerPorts:
    """Returns the local-testcontainer's ports.

    Retries up to one second before failing.
    """
    ports = None
    ports_start_time = time.monotonic()
    while not ports and time.monotonic() - ports_start_time < 1:
        ports = _get_ports(name)
        if not ports:
            time.sleep(0.1)

    if not ports:
        _echo_bad("Failed to get ports from container.")
        sys.exit(1)

    return ports


def _get_ports(name: str) -> _WandbContainerPorts | None:
    """Query the container's ports.

    Returns None if the container's ports are not available yet. On occasion,
    `docker port` doesn't return all ports if it happens too soon after
    `docker run`.
    """
    ports_str = subprocess.check_output(["docker", "port", name]).decode()

    port_line_re = re.compile(r"(\d+)(\/\w+)? -> [^:]*:(\d+)")
    base_port = 0
    fixture_port = 0
    for line in ports_str.splitlines():
        match = port_line_re.fullmatch(line)
        if not match:
            continue

        internal_port = match.group(1)
        external_port = match.group(3)

        if internal_port == "8080":
            base_port = int(external_port)
        elif internal_port == "9015":
            fixture_port = int(external_port)

    if not base_port:
        return None
    if not fixture_port:
        return None

    return _WandbContainerPorts(
        base_port=base_port,
        fixture_port=fixture_port,
    )


def _echo_good(msg: str) -> None:
    msg = click.style(msg, fg="green")
    prefix = click.style("local_wandb_server.py", bold=True)
    click.echo(f"{prefix}: {msg}", err=True)


def _echo_info(msg: str) -> None:
    prefix = click.style("local_wandb_server.py", bold=True)
    click.echo(f"{prefix}: {msg}", err=True)


def _echo_bad(msg: str) -> None:
    msg = click.style(msg, fg="red")
    prefix = click.style("local_wandb_server.py", bold=True)
    click.echo(f"{prefix}: {msg}", err=True)


if __name__ == "__main__":
    main()
