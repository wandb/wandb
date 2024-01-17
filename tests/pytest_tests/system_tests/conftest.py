import dataclasses
import json
import os
import platform
import secrets
import string
import subprocess
import time
import unittest.mock
import urllib.parse
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Union

import pytest
import requests
import wandb
import wandb.old.settings
import wandb.util
from wandb.testing.relay import (
    DeliberateHTTPError,
    InjectedResponse,
    RelayServer,
    TokenizedCircularPattern,
)

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


# `local-testcontainer` ports
LOCAL_BASE_PORT = "8080"
SERVICES_API_PORT = "8083"
FIXTURE_SERVICE_PORT = "9015"


class ConsoleFormatter:
    BOLD = "\033[1m"
    CODE = "\033[2m"
    MAGENTA = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"


# --------------------------------
# Fixtures for full test point
# --------------------------------
@dataclasses.dataclass
class UserFixtureCommand:
    command: Literal["up", "down", "down_all", "logout", "login", "password"]
    username: Optional[str] = None
    password: Optional[str] = None
    admin: bool = False
    endpoint: str = "db/user"
    port: str = FIXTURE_SERVICE_PORT
    method: Literal["post"] = "post"


@dataclasses.dataclass
class AddAdminAndEnsureNoDefaultUser:
    email: str
    password: str
    endpoint: str = "api/users-admin"
    port: str = SERVICES_API_PORT
    method: Literal["put"] = "put"


@dataclasses.dataclass
class WandbServerSettings:
    name: str
    volume: str
    wandb_server_pull: str
    wandb_server_image_registry: str
    wandb_server_image_repository: str
    wandb_server_tag: str
    # ports exposed to the host
    local_base_port: str
    services_api_port: str
    fixture_service_port: str
    # ports internal to the container
    internal_local_base_port: str = LOCAL_BASE_PORT
    internal_local_services_api_port: str = SERVICES_API_PORT
    internal_fixture_service_port: str = FIXTURE_SERVICE_PORT
    url: str = "http://localhost"

    base_url: Optional[str] = None

    def __post_init__(self):
        self.base_url = f"{self.url}:{self.local_base_port}"


def pytest_addoption(parser):
    # note: we default to "function" scope to ensure the environment is
    # set up properly when running the tests in parallel with pytest-xdist.
    parser.addoption(
        "--user-scope",
        default="function",  # or "function" or "session" or "module"
        help='cli to set scope of fixture "user-scope"',
    )
    parser.addoption(
        "--base-url",
        default=f"http://localhost:{LOCAL_BASE_PORT}",
        help='cli to set "base-url"',
    )
    parser.addoption(
        "--wandb-server-image-registry",
        default="us-central1-docker.pkg.dev",
        help="Image registry to use for the wandb server",
    )
    parser.addoption(
        "--wandb-server-image-repository",
        default="wandb-production/images/local-testcontainer",
        # images corresponding to past local releases:
        # default="wandb-client-cicd/images/local-testcontainer",
        help="Image repository to use for the wandb server",
    )
    parser.addoption(
        "--wandb-server-tag",
        default="master",
        help="Image tag to use for the wandb server",
    )
    parser.addoption(
        "--wandb-server-pull",
        default="always",
        choices=["always", "missing", "never"],
        help="Force pull the latest wandb server image",
    )
    # debug option: creates an admin account that can be used to log in to the
    # app and inspect the test runs.
    parser.addoption(
        "--wandb-debug",
        action="store_true",
        default=False,
        help="Run tests in debug mode",
    )
    parser.addoption(
        "--wandb-verbose",
        action="store_true",
        default=False,
        help="Run tests in verbose mode",
    )


def random_string(length: int = 12) -> str:
    """Generate a random string of a given length.

    :param length: Length of the string to generate.
    :return: Random string.
    """
    return "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length)
    )


def determine_scope(fixture_name, config):
    return config.getoption("--user-scope")


@pytest.fixture(scope="session")
def base_url(request):
    return request.config.getoption("--base-url")


@pytest.fixture(scope="session")
def wandb_debug(request):
    return request.config.getoption("--wandb-debug", default=False)


@pytest.fixture(scope="session")
def wandb_verbose(request):
    return request.config.getoption("--wandb-verbose", default=False)


def check_server_health(
    base_url: str, endpoint: str, num_retries: int = 1, sleep_time: int = 1
) -> bool:
    """Check if wandb server is healthy.

    :param base_url:
    :param num_retries:
    :param sleep_time:
    :return:
    """
    for _ in range(num_retries):
        try:
            response = requests.get(urllib.parse.urljoin(base_url, endpoint))
            if response.status_code == 200:
                return True
            time.sleep(sleep_time)
        except requests.exceptions.ConnectionError:
            time.sleep(sleep_time)
    return False


@pytest.fixture(scope="session")
def user_factory(worker_id: str, wandb_debug) -> str:
    def _user_factory(fixture_fn, settings):
        username = f"user-{worker_id}-{random_string()}"
        command = UserFixtureCommand(
            command="up", username=username, port=settings.fixture_service_port
        )
        fixture_fn(command)
        command = UserFixtureCommand(
            command="password",
            username=username,
            password=username,
            port=settings.fixture_service_port,
        )
        fixture_fn(command)

        with unittest.mock.patch.dict(
            os.environ,
            {
                "WANDB_API_KEY": username,
                "WANDB_ENTITY": username,
                "WANDB_USERNAME": username,
                "WANDB_BASE_URL": f"http://localhost:{settings.local_base_port}",
            },
        ):
            yield username

            if not wandb_debug:
                command = UserFixtureCommand(
                    command="down",
                    username=username,
                    port=settings.fixture_service_port,
                )
                fixture_fn(command)

    yield _user_factory


@pytest.fixture(scope="session")
def fixture_fn_factory():
    def _fixture_fn_factory(settings):
        def fixture_util(
            cmd: Union[UserFixtureCommand, AddAdminAndEnsureNoDefaultUser]
        ) -> bool:
            base_url = settings.base_url
            endpoint = urllib.parse.urljoin(
                base_url.replace(settings.local_base_port, cmd.port),
                cmd.endpoint,
            )

            if isinstance(cmd, UserFixtureCommand):
                data = {"command": cmd.command}
                if cmd.username:
                    data["username"] = cmd.username
                if cmd.password:
                    data["password"] = cmd.password
                if cmd.admin is not None:
                    data["admin"] = cmd.admin
            elif isinstance(cmd, AddAdminAndEnsureNoDefaultUser):
                data = [
                    {"email": f"{cmd.email}@wandb.com", "password": cmd.password},
                ]
            else:
                raise NotImplementedError(f"{cmd} is not implemented")
            # trigger fixture
            print(f"Triggering fixture on {endpoint}: {data}")
            # response = getattr(requests, cmd.method)(
            #     endpoint,
            #     json=data,
            #     headers={
            #         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:66.0) Gecko/20100101 Firefox/66.0",
            #         "Accept-Encoding": "*",
            #         "Connection": "keep-alive",
            #     },
            # )
            response = getattr(requests, cmd.method)(endpoint, json=data)

            if response.status_code != 200:
                print(response.json())
                return False
            return True

        # todo: remove this once testcontainer is available on Win
        if platform.system() == "Windows":
            pytest.skip("testcontainer is not available on Win")

        yield fixture_util

    yield _fixture_fn_factory


def wandb_server_factory():
    def _wandb_server_factory(settings: WandbServerSettings) -> (bool, Optional[int]):
        base_url = settings.base_url
        app_health_endpoint = "healthz"
        fixture_url = base_url.replace(
            settings.local_base_port, settings.fixture_service_port
        )
        fixture_health_endpoint = "health"

        if os.environ.get("CI") == "true":
            return (
                check_server_health(base_url=base_url, endpoint=app_health_endpoint),
                None,
            )

        if not check_server_health(base_url, app_health_endpoint):
            command = [
                "docker",
                "run",
                "--pull",
                settings.wandb_server_pull,
                "--rm",
                "-v",
                f"{settings.volume}:/vol",
                "-p",
                f"{settings.local_base_port}:{settings.internal_local_base_port}",
                "-p",
                f"{settings.services_api_port}:{settings.internal_local_services_api_port}",
                "-p",
                f"{settings.fixture_service_port}:{settings.internal_fixture_service_port}",
                "-e",
                "WANDB_ENABLE_TEST_CONTAINER=true",
                "--name",
                settings.name,
                "--platform",
                "linux/amd64",
                f"{settings.wandb_server_image_registry}/{settings.wandb_server_image_repository}:{settings.wandb_server_tag}",
            ]
            server_process = subprocess.Popen(command)
            # wait for the server to start
            server_is_up = check_server_health(
                base_url=base_url, endpoint=app_health_endpoint, num_retries=30
            )
            if not server_is_up:
                return False, None
            # check that the fixture service is accessible
            return (
                check_server_health(
                    base_url=fixture_url,
                    endpoint=fixture_health_endpoint,
                    num_retries=30,
                ),
                server_process.pid,
            )

        return (
            check_server_health(
                base_url=fixture_url, endpoint=fixture_health_endpoint, num_retries=10
            ),
            None,
        )

    return _wandb_server_factory


def pytest_configure(config):
    print("Running tests with wandb version:", wandb.__version__)
    print("Configuring wandb server...")

    settings = WandbServerSettings(
        name="wandb-local-testcontainer",
        volume="wandb-local-testcontainer-vol",
        local_base_port=LOCAL_BASE_PORT,
        services_api_port=SERVICES_API_PORT,
        fixture_service_port=FIXTURE_SERVICE_PORT,
        wandb_server_pull=config.getoption("--wandb-server-pull"),
        wandb_server_image_registry=config.getoption("--wandb-server-image-registry"),
        wandb_server_image_repository=config.getoption(
            "--wandb-server-image-repository"
        ),
        wandb_server_tag=config.getoption("--wandb-server-tag"),
    )
    config.wandb_server_settings = settings

    # start or connect to wandb test server
    success, pid = wandb_server_factory()(settings)
    if not success:
        pytest.exit("Failed to connect to wandb server")
    if pid:
        config.wandb_server_pid = pid


# TODO: add pytest_unconfigure to clean up the wandb server


@pytest.fixture(scope="session")
def fixture_fn(request, fixture_fn_factory):
    yield from fixture_fn_factory(request.config.wandb_server_settings)


@pytest.fixture(scope=determine_scope)
def user(request, user_factory, fixture_fn):
    yield from user_factory(fixture_fn, request.config.wandb_server_settings)


@pytest.fixture(scope="session", autouse=True)
def debug(wandb_debug, fixture_fn, base_url):
    if wandb_debug:
        admin_username = f"admin-{random_string()}"
        # disable default user and create an admin account that can be used to log in to the app
        # and inspect the test runs.
        command = UserFixtureCommand(command="down", username="local@wandb.com")
        fixture_fn(command)
        command = UserFixtureCommand(
            command="up",
            username=admin_username,
            admin=True,
        )
        fixture_fn(command)

        command = UserFixtureCommand(
            command="password",
            username=admin_username,
            password=admin_username,
            admin=True,
        )
        fixture_fn(command)

        command = AddAdminAndEnsureNoDefaultUser(
            email=admin_username,
            password=admin_username,
        )
        fixture_fn(command)
        message = (
            f"{ConsoleFormatter.GREEN}"
            "*****************************************************************\n"
            "Admin user created for debugging:\n"
            f"Proceed to {base_url} and log in with the following credentials:\n"
            f"username: {admin_username}@wandb.com\n"
            f"password: {admin_username}\n"
            "*****************************************************************"
            f"{ConsoleFormatter.END}"
        )
        print(message)
        yield admin_username
        print(message)
        # input("\nPress any key to exit...")
        # command = UserFixtureCommand(command="down_all")
        # fixture_fn(command)
    else:
        yield None


@pytest.fixture(scope="function")
def relay_server(base_url, wandb_verbose):
    """Create a new relay server."""

    @contextmanager
    def relay_server_context(inject: Optional[List[InjectedResponse]] = None):
        _relay_server = RelayServer(
            base_url=base_url,
            inject=inject,
            verbose=wandb_verbose,
        )
        try:
            _relay_server.start()
            print(f"Relay server started at {_relay_server.relay_url}")
            with unittest.mock.patch.dict(
                os.environ,
                {"WANDB_BASE_URL": _relay_server.relay_url},
            ):
                yield _relay_server
            print(f"Stopping relay server at {_relay_server.relay_url}")
        finally:
            del _relay_server

    return relay_server_context


@pytest.fixture(scope="function")
def wandb_init(user, test_settings, request):
    # mirror wandb.sdk.wandb_init.init args, overriding name and entity defaults
    def init(
        job_type: Optional[str] = None,
        dir: Optional[str] = None,
        config: Union[Dict, str, None] = None,
        project: Optional[str] = None,
        entity: Optional[str] = None,
        reinit: bool = None,
        tags: Optional[Sequence] = None,
        group: Optional[str] = None,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        magic: Union[dict, str, bool] = None,
        config_exclude_keys: Optional[List[str]] = None,
        config_include_keys: Optional[List[str]] = None,
        anonymous: Optional[str] = None,
        mode: Optional[str] = None,
        allow_val_change: Optional[bool] = None,
        resume: Optional[Union[bool, str]] = None,
        force: Optional[bool] = None,
        tensorboard: Optional[bool] = None,
        sync_tensorboard: Optional[bool] = None,
        monitor_gym: Optional[bool] = None,
        save_code: Optional[bool] = None,
        id: Optional[str] = None,
        settings: Union[
            "wandb.sdk.wandb_settings.Settings", Dict[str, Any], None
        ] = None,
    ):
        kwargs = dict(locals())
        # drop fixtures from kwargs
        for key in ("user", "test_settings", "request"):
            kwargs.pop(key, None)
        # merge settings from request with test_settings
        request_settings = kwargs.pop("settings", dict())
        kwargs["name"] = kwargs.pop("name", request.node.name)

        run = wandb.init(
            settings=test_settings(request_settings),
            **kwargs,
        )
        return run

    wandb._IS_INTERNAL_PROCESS = False
    yield init
    # note: this "simulates" a wandb.init function, so you would have to do
    # something like: run = wandb_init(...); ...; run.finish()


@pytest.fixture(scope="function")
def server_context(base_url):
    class ServerContext:
        def __init__(self) -> None:
            self.api = wandb.Api(overrides={"base_url": base_url})

        def get_run(self, run: "wandb.sdk.wandb_run.Run") -> "wandb.apis.public.Run":
            return self.api.run(run.path)

    yield ServerContext()


# Injected responses
@pytest.fixture(scope="function")
def inject_file_stream_response(base_url, user):
    def helper(
        run,
        body: Union[str, Exception] = "{}",
        status: int = 200,
        application_pattern: str = "1",
    ) -> InjectedResponse:
        if status > 299:
            message = body if isinstance(body, str) else "::".join(body.args)
            body = DeliberateHTTPError(status_code=status, message=message)
        return InjectedResponse(
            method="POST",
            url=(
                urllib.parse.urljoin(
                    base_url,
                    f"/files/{user}/{run.project or 'uncategorized'}/{run.id}/file_stream",
                )
            ),
            body=body,
            status=status,
            application_pattern=TokenizedCircularPattern(application_pattern),
        )

    yield helper


@pytest.fixture(scope="function")
def inject_graphql_response(base_url, user):
    def helper(
        body: Union[str, Exception] = "{}",
        status: int = 200,
        query_match_fn=None,
        application_pattern: str = "1",
    ) -> InjectedResponse:
        def match(self, request):
            body = json.loads(request.body)
            return query_match_fn(body["query"], body.get("variables"))

        if status > 299:
            message = body if isinstance(body, str) else "::".join(body.args)
            body = DeliberateHTTPError(status_code=status, message=message)

        return InjectedResponse(
            # request
            method="POST",
            url=urllib.parse.urljoin(base_url, "/graphql"),
            custom_match_fn=match if query_match_fn else None,
            application_pattern=TokenizedCircularPattern(application_pattern),
            # response
            body=body,
            status=status,
        )

    yield helper
