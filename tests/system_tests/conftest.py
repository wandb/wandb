from __future__ import annotations

import os
from typing import Generator, Iterator

import pytest

from .wandb_backend_spy import WandbBackendProxy, WandbBackendSpy, spy_proxy

# https://docs.pytest.org/en/stable/how-to/plugins.html#requiring-loading-plugins-in-a-test-module-or-conftest-file
pytest_plugins = ("tests.system_tests.backend_fixtures",)


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
def user(mocker, backend_fixture_factory) -> Iterator[str]:
    username = backend_fixture_factory.make_user()
    envvars = {
        "WANDB_API_KEY": username,
        "WANDB_ENTITY": username,
        "WANDB_USERNAME": username,
    }
    mocker.patch.dict(os.environ, envvars)
    yield username


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
