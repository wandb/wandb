from __future__ import annotations

import contextlib
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from typing import Callable

import pytest
import wandb

from tests.fixtures.wandb_backend_spy import (
    WandbBackendProxy,
    WandbBackendSpy,
    spy_proxy,
)

from .backend_fixtures import (
    BackendFixtureFactory,
    LocalWandbBackendAddress,
    connect_to_local_wandb_backend,
)


@pytest.fixture(scope="session")
def local_wandb_backend() -> LocalWandbBackendAddress:
    """Fixture that starts up or connects to the local-testcontainer.

    This does not patch WANDB_BASE_URL! Use `use_local_wandb_backend` instead.
    """
    return connect_to_local_wandb_backend(name="wandb-local-testcontainer")


@pytest.fixture(scope="session")
def local_wandb_backend_importers() -> LocalWandbBackendAddress:
    """Fixture that starts up or connects to a second local-testcontainer.

    This is used by importer tests, to move data between two backends.
    """
    return connect_to_local_wandb_backend(name="wandb-local-testcontainer-importers")


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


@pytest.fixture(scope="session")
def backend_fixture_factory(
    worker_id: str,
    local_wandb_backend: LocalWandbBackendAddress,
    use_local_wandb_backend: None,
) -> Generator[BackendFixtureFactory, None, None]:
    _ = use_local_wandb_backend
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


# --------------------------------
# Fixtures for full test point
# --------------------------------


def pytest_addoption(parser: pytest.Parser):
    parser.addoption(
        "--wandb-verbose",
        action="store_true",
        default=False,
        help="Run tests in verbose mode",
    )


@pytest.fixture(scope="session")
def wandb_verbose(request):
    return request.config.getoption("--wandb-verbose", default=False)


@pytest.fixture
def user(
    request: pytest.FixtureRequest,
    backend_fixture_factory: BackendFixtureFactory,
) -> Iterator[str]:
    """A user created for the duration of a test.

    This cannot be used together with module_user. If module_user is also
    requested by the test or one of its fixtures, this raises an error.

    Sets login-related environment variables.
    """
    if "module_user" in request.fixturenames:
        message = "Cannot use `user` and `module_user` fixtures together."
        raise AssertionError(message)

    with _user(backend_fixture_factory) as user:
        yield user


@pytest.fixture(scope="module")
def module_user(
    backend_fixture_factory: BackendFixtureFactory,
) -> Iterator[str]:
    """A new user shared by all tests in a module.

    Just like `user`, but is shared by multiple tests.

    This is used in some test files with many tests where mutating the same
    test user's data does not affect correctness, and creating a user for
    each test is slow.
    """
    with _user(backend_fixture_factory) as user:
        yield user


@contextlib.contextmanager
def _user(backend_fixture_factory: BackendFixtureFactory) -> Iterator[str]:
    username = backend_fixture_factory.make_user()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("WANDB_API_KEY", username)
        monkeypatch.setenv("WANDB_ENTITY", username)
        monkeypatch.setenv("WANDB_USERNAME", username)

        yield username


@pytest.fixture
@pytest.mark.usefixtures("skip_verify_login")
def api(user: str) -> wandb.Api:
    """A wandb.Api that can be used for the duration of a test."""
    return wandb.Api(api_key=user)


@pytest.fixture
def module_api(make_module_api: Callable[[], wandb.Api]) -> wandb.Api:
    """A wandb.Api using the `module_user` fixture.

    Despite the name, this is function-scoped and exists only to force tests
    to be explicit when they rely on `module_user`.

    Module-scoped fixtures should use `make_module_api` directly.
    """
    return make_module_api()


@pytest.fixture(scope="module")
@pytest.mark.usefixtures("skip_verify_login")
def make_module_api(module_user: str) -> Callable[[], wandb.Api]:
    """A callback that creates a wandb.Api using the `module_user` fixture.

    The returned object becomes invalid after `wandb.teardown()`, which is
    called between tests.
    """

    def callback() -> wandb.Api:
        return wandb.Api(api_key=module_user)

    return callback


@dataclass
class UserOrg:
    username: str
    organization_names: list[str]


@pytest.fixture
def user_in_orgs_factory(
    backend_fixture_factory: BackendFixtureFactory,
    user: str,
) -> Iterator[Callable[[int], UserOrg]]:
    """Fixture that provides a factory function to create a user and associated orgs.

    Usage in a test:
        def test_something(user_in_orgs_factory):
            # Get a user with 2 organizations
            user_org_data = user_in_orgs_factory(number_of_orgs=2)

            # Get a user with the default (1) organization
            user_org_data_default = user_in_orgs_factory()
    """

    def _factory(number_of_orgs: int = 1) -> UserOrg:
        """Creates organizations for the pre-defined user."""
        if number_of_orgs <= 0:
            raise ValueError("Number of organizations have to be positive.")
        try:
            orgs = [
                backend_fixture_factory.make_org(username=user)
                for _ in range(number_of_orgs)
            ]
        except Exception as e:
            pytest.skip(
                "Failed to fetch organization fixture. "
                "This is most likely due to an older wandb server version. "
                f"Error: {e}",
            )

        return UserOrg(username=user, organization_names=orgs)

    yield _factory


@pytest.fixture(scope="session")
def wandb_backend_proxy_server(
    local_wandb_backend,
) -> Generator[WandbBackendProxy, None, None]:
    """Session fixture that starts up a proxy server for the W&B backend."""
    with spy_proxy(
        target_host=local_wandb_backend.host,
        target_port=local_wandb_backend.base_port,
    ) as proxy:
        yield proxy


@pytest.fixture(scope="function")
def wandb_backend_spy(
    user,
    wandb_backend_proxy_server: WandbBackendProxy,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[WandbBackendSpy, None, None]:
    """Fixture that allows spying on requests to the W&B backend.

    This patches WANDB_BASE_URL and creates a fake user for the test
    setting auth-related environment variables.

    Usage:

        def test_something(wandb_backend_spy):
            with wandb.init() as run:
                run.log({"x": 1})

            with wandb_backend_spy.freeze() as snapshot:
                history = snapshot.history(run_id=run.id)
                assert history[0]["x"] == 1
    """

    # Use a fake API key for the test.
    _ = user

    # Connect to the proxy to spy on requests:
    monkeypatch.setenv(
        "WANDB_BASE_URL",
        f"http://127.0.0.1:{wandb_backend_proxy_server.port}",
    )

    with wandb_backend_proxy_server.spy() as spy:
        yield spy
