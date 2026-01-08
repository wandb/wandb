from __future__ import annotations

import logging
import os
import pathlib
import shutil
import sys
import time
import unittest.mock
from collections.abc import Generator, Iterator
from pathlib import Path
from queue import Queue
from typing import Any, Callable

from wandb.sdk import wandb_setup

# Don't write to Sentry in wandb.
os.environ["WANDB_ERROR_REPORTING"] = "false"

import git
import pytest
import wandb
import wandb.util
from click.testing import CliRunner
from wandb import Api
from wandb.errors import term
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.lib import filesystem, module, runid, wbauth
from wandb.sdk.lib.gitlib import GitRepo
from wandb.sdk.lib.paths import StrPath

pytest_plugins = [
    "tests.fixtures.emulated_terminal",
    "tests.fixtures.mock_wandb_log",
]

# --------------------------------
# Global pytest configuration
# --------------------------------


@pytest.fixture(autouse=True)
def setup_wandb_env_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configures wandb env variables to suitable defaults for tests."""
    # Set the _network_buffer setting to 1000 to increase the likelihood
    # of triggering flow control logic.
    monkeypatch.setenv("WANDB_X_NETWORK_BUFFER", "1000")


# --------------------------------
# Misc Fixtures utilities
# --------------------------------


@pytest.fixture(scope="session")
def assets_path() -> Generator[Callable[[StrPath], Path], None, None]:
    assets_dir = Path(__file__).resolve().parent / "assets"

    def assets_path_fn(path: StrPath) -> Path:
        return assets_dir / path

    yield assets_path_fn


@pytest.fixture
def copy_asset(
    assets_path,
) -> Generator[Callable[[StrPath, StrPath | None], Path], None, None]:
    def copy_asset_fn(path: StrPath, dst: StrPath | None = None) -> Path:
        src = assets_path(path)
        if src.is_file():
            return shutil.copy(src, dst or path)
        return shutil.copytree(src, dst or path)

    yield copy_asset_fn


# --------------------------------
# Misc Fixtures
# --------------------------------


@pytest.fixture()
def wandb_caplog(
    caplog: pytest.LogCaptureFixture,
) -> Iterator[pytest.LogCaptureFixture]:
    """Modified caplog fixture that detect wandb log messages.

    The wandb logger is configured to not propagate messages to the root logger,
    so caplog does not work out of the box.
    """

    logger = logging.getLogger("wandb")

    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


@pytest.fixture(autouse=True)
def reset_logger():
    """Resets the `wandb.errors.term` module before each test."""
    wandb.termsetup(wandb.Settings(silent=False), None)
    term._dynamic_blocks = []


@pytest.fixture(scope="function", autouse=True)
def filesystem_isolate(tmp_path, monkeypatch):
    # isolated_filesystem() changes the current working directory, which is
    # where coverage.py stores coverage by default. This causes Python
    # subprocesses to place their coverage into a temporary directory that is
    # discarded after each test.
    #
    # Setting COVERAGE_FILE to an absolute path fixes this.
    if covfile := os.getenv("COVERAGE_FILE"):
        new_covfile = str(pathlib.Path(covfile).absolute())
    else:
        new_covfile = str(pathlib.Path(os.getcwd()) / ".coverage")

    print(f"Setting COVERAGE_FILE to {new_covfile}", file=sys.stderr)
    monkeypatch.setenv("COVERAGE_FILE", new_covfile)

    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        yield


# todo: this fixture should probably be autouse=True
@pytest.fixture(scope="function", autouse=False)
def local_settings(tmp_path: pathlib.Path, filesystem_isolate):
    """Place global settings in an isolated dir."""
    # Ensure local settings are also in an isolated directory.
    _ = filesystem_isolate

    config_path = tmp_path / "test-wandb-config"
    wandb_setup.singleton().settings.settings_system = str(config_path)


@pytest.fixture(scope="function", autouse=True)
def local_netrc(filesystem_isolate):
    """Never use our real credentials, put them in their own isolated dir."""
    # patch os.environ NETRC
    with unittest.mock.patch.dict(
        "os.environ",
        {"NETRC": os.path.realpath("netrc")},
    ):
        yield


@pytest.fixture
def dummy_api_key() -> str:
    return "1824812581259009ca9981580f8f8a9012409eee"


@pytest.fixture
def patch_apikey(dummy_api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a fake API key and W&B server URL in a test."""
    dummy_url = "https://dummy"

    # Both are needed because of the way InternalApi gets the base URL.
    monkeypatch.setenv("WANDB_BASE_URL", dummy_url)
    wandb_setup.singleton().settings.base_url = dummy_url

    # Api tries to load the default entity from the fake URL in unit tests.
    monkeypatch.setenv("WANDB_ENTITY", "test-entity")

    wbauth.use_explicit_auth(
        auth=wbauth.AuthApiKey(api_key=dummy_api_key, host=dummy_url),
        source="test",
    )


@pytest.fixture
def skip_verify_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch `wandb.Api` to not verify the API key."""
    from wandb.apis.public import api

    monkeypatch.setattr(
        api.wandb_login,
        "_verify_login",
        unittest.mock.MagicMock(),
    )


@pytest.fixture
def patch_prompt(monkeypatch):
    monkeypatch.setattr(
        wandb.util,
        "prompt_choices",
        lambda x, input_timeout=None: x[0],
    )


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch):
    # Allow terminput() usage when invoking with the CliRunner.
    #
    # This assumes that terminput() is only called within a runner.invoke()
    # in tests that use the runner fixture.
    monkeypatch.setattr(term, "can_use_terminput", lambda: True)
    return CliRunner()


@pytest.fixture
def git_repo(runner):
    with runner.isolated_filesystem(), git.Repo.init(".") as repo:
        filesystem.mkdir_exists_ok("wandb")
        # Because the forked process doesn't use my monkey patch above
        with open(os.path.join("wandb", "settings"), "w") as f:
            f.write("[default]\nproject: test")
        open("README", "wb").close()
        repo.index.add(["README"])
        repo.index.commit("Initial commit")
        yield GitRepo(lazy=False)


@pytest.fixture(scope="function", autouse=True)
def unset_global_objects():
    from wandb.sdk.lib.module import unset_globals

    yield
    unset_globals()


@pytest.fixture(scope="session", autouse=True)
def env_teardown():
    wandb.teardown()
    yield
    wandb.teardown()
    if not os.environ.get("CI") == "true":
        # TODO: uncomment this for prod? better make controllable with an env var
        # subprocess.run(["wandb", "server", "stop"])
        pass


@pytest.fixture(scope="function", autouse=True)
def clean_up():
    yield
    wandb.teardown()


@pytest.fixture
def api() -> Api:
    with unittest.mock.patch("wandb.sdk.wandb_login._verify_login"):
        return Api()


# --------------------------------
# Fixtures for user test point
# --------------------------------


@pytest.fixture()
def record_q() -> Queue:
    return Queue()


@pytest.fixture()
def mocked_interface(record_q: Queue) -> InterfaceQueue:
    return InterfaceQueue(record_q=record_q)


@pytest.fixture
def mocked_backend(mocked_interface: InterfaceQueue) -> Generator[object, None, None]:
    class MockedBackend:
        def __init__(self) -> None:
            self.interface = mocked_interface

    yield MockedBackend()


@pytest.fixture(scope="function")
def test_settings():
    def update_test_settings(
        extra_settings: dict | wandb.Settings | None = None,
    ):
        if not extra_settings:
            extra_settings = dict()

        settings = wandb.Settings(
            console="off",
            save_code=False,
        )
        if isinstance(extra_settings, dict):
            settings.update_from_dict(extra_settings)
        elif isinstance(extra_settings, wandb.Settings):
            settings.update_from_settings(extra_settings)
        settings.x_start_time = time.time()
        return settings

    yield update_test_settings


@pytest.fixture(scope="function")
def mock_run(test_settings, mocked_backend) -> Generator[Callable, None, None]:
    """Create a Run object with a stubbed out 'backend'.

    This is similar to using `wandb.init(mode="offline")`, but much faster
    as it does not start up a service process.

    This is intended for tests that need to exercise surface-level Python logic
    in the Run class. Note that it's better to factor out such logic into its
    own unit-tested module instead.
    """

    def mock_run_fn(use_magic_mock=False, **kwargs: Any) -> wandb.Run:
        kwargs_settings = kwargs.pop("settings", dict())
        kwargs_settings = {
            "run_id": runid.generate_id(),
            **dict(kwargs_settings),
        }
        run = wandb.Run(settings=test_settings(kwargs_settings), **kwargs)
        run._set_backend(
            unittest.mock.MagicMock() if use_magic_mock else mocked_backend
        )
        run._set_library(unittest.mock.MagicMock())

        module.set_global(
            run=run,
            config=run.config,
            log=run.log,
            summary=run.summary,
            save=run.save,
            use_artifact=run.use_artifact,
            log_artifact=run.log_artifact,
            define_metric=run.define_metric,
            alert=run.alert,
            watch=run.watch,
            unwatch=run.unwatch,
        )

        return run

    yield mock_run_fn
    module.unset_globals()


@pytest.fixture
def example_file(tmp_path: Path) -> Path:
    new_file = tmp_path / "test.txt"
    new_file.write_text("hello")
    return new_file


@pytest.fixture
def example_files(tmp_path: Path) -> Path:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (artifact_dir / f"artifact_{i}.txt").write_text(f"file-{i}")
    return artifact_dir
