from __future__ import annotations

import logging
import os
import pathlib
import shutil
import sys
import time
import unittest.mock
from itertools import takewhile
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Generator, Iterable, Iterator

import pyte
import pyte.modes
from pytest_mock import MockerFixture
from wandb.errors import term

# Don't write to Sentry in wandb.
os.environ["WANDB_ERROR_REPORTING"] = "false"

import git
import pytest
import wandb
import wandb.old.settings
import wandb.sdk.lib.apikey
import wandb.util
from click.testing import CliRunner
from wandb import Api
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.lib import filesystem, module, runid
from wandb.sdk.lib.gitlib import GitRepo
from wandb.sdk.lib.paths import StrPath

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


class MockWandbTerm:
    """Helper to test wandb.term*() calls.

    See the `mock_wandb_log` fixture.
    """

    def __init__(
        self,
        termlog: unittest.mock.MagicMock,
        termwarn: unittest.mock.MagicMock,
        termerror: unittest.mock.MagicMock,
    ):
        self._termlog = termlog
        self._termwarn = termwarn
        self._termerror = termerror

    def logged(self, msg: str) -> bool:
        """Returns whether the message was included in a termlog()."""
        return self._logged(self._termlog, msg)

    def warned(self, msg: str) -> bool:
        """Returns whether the message was included in a termwarn()."""
        return self._logged(self._termwarn, msg)

    def errored(self, msg: str) -> bool:
        """Returns whether the message was included in a termerror()."""
        return self._logged(self._termerror, msg)

    def _logged(self, termfunc: unittest.mock.MagicMock, msg: str) -> bool:
        return any(msg in logged for logged in self._logs(termfunc))

    def _logs(self, termfunc: unittest.mock.MagicMock) -> Iterable[str]:
        # All the term*() functions have a similar API: the message is the
        # first argument, which may also be passed as a keyword argument called
        # "string".
        for call in termfunc.call_args_list:
            if "string" in call.kwargs:
                yield call.kwargs["string"]
            else:
                yield call.args[0]


@pytest.fixture()
def mock_wandb_log() -> Generator[MockWandbTerm, None, None]:
    """Mocks the wandb.term*() methods for a test.

    This patches the termlog() / termwarn() / termerror() methods and returns
    a `MockWandbTerm` object that can be used to assert on their usage.

    The logging functions mutate global state (for repeat=False), making
    them unsuitable for tests. Use this fixture to assert that a message
    was logged.
    """
    # NOTE: This only stubs out calls like "wandb.termlog()", NOT
    # "from wandb.errors.term import termlog; termlog()".
    with unittest.mock.patch.multiple(
        "wandb",
        termlog=unittest.mock.DEFAULT,
        termwarn=unittest.mock.DEFAULT,
        termerror=unittest.mock.DEFAULT,
    ) as patched:
        yield MockWandbTerm(
            patched["termlog"],
            patched["termwarn"],
            patched["termerror"],
        )


class EmulatedTerminal:
    """The return value of the emulated_terminal fixture."""

    def __init__(self, capsys: pytest.CaptureFixture[str]):
        self._capsys = capsys
        self._screen = pyte.Screen(80, 24)
        self._screen.set_mode(pyte.modes.LNM)  # \n implies \r
        self._stream = pyte.Stream(self._screen)

    def reset_capsys(self) -> None:
        """Resets pytest's captured stderr and stdout buffers."""
        self._capsys.readouterr()

    def read_stderr(self) -> list[str]:
        """Returns the text in the emulated terminal.

        This processes the stderr text captured by pytest since the last
        invocation and returns the updated state of the screen. Empty lines
        at the top and bottom of the screen and empty text at the end of
        any line are trimmed.

        NOTE: This resets pytest's stderr and stdout buffers. You should not
        use this with anything else that uses capsys.
        """
        self._stream.feed(self._capsys.readouterr().err)

        lines = [line.rstrip() for line in self._screen.display]

        # Trim empty lines from the start and end of the screen.
        n_empty_at_start = sum(1 for _ in takewhile(lambda line: not line, lines))
        n_empty_at_end = sum(1 for _ in takewhile(lambda line: not line, lines[::-1]))
        return lines[n_empty_at_start:-n_empty_at_end]


@pytest.fixture()
def emulated_terminal(monkeypatch, capsys) -> EmulatedTerminal:
    """Emulates a terminal for the duration of a test.

    This makes functions in the `wandb.errors.term` module act as if
    stderr is a terminal.

    NOTE: This resets pytest's stderr and stdout buffers. You should not
    use this with anything else that uses capsys.
    """

    monkeypatch.setenv("TERM", "xterm")

    monkeypatch.setattr(term, "_sys_stderr_isatty", lambda: True)

    # Make click pretend we're a TTY, so it doesn't strip ANSI sequences.
    # This is fragile and could break when click is updated.
    monkeypatch.setattr("click._compat.isatty", lambda *args, **kwargs: True)

    return EmulatedTerminal(capsys)


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
def local_settings(filesystem_isolate):
    """Place global settings in an isolated dir."""
    config_path = os.path.join(os.getcwd(), ".config", "wandb", "settings")
    filesystem.mkdir_exists_ok(os.path.join(".config", "wandb"))

    # todo: this breaks things in unexpected places
    # todo: get rid of wandb.old
    with unittest.mock.patch.object(
        wandb.old.settings.Settings,
        "_global_path",
        return_value=config_path,
    ):
        yield


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
def patch_apikey(mocker: MockerFixture, dummy_api_key: str):
    mocker.patch.object(wandb.sdk.lib.apikey, "isatty", return_value=True)
    mocker.patch.object(wandb.sdk.lib.apikey, "input", return_value=1)
    mocker.patch.object(wandb.sdk.lib.apikey, "getpass", return_value=dummy_api_key)


@pytest.fixture
def skip_verify_login(monkeypatch):
    """Patches the `_verify_login` method to do nothing.

    This method is called whenever wandb.login is called.
    """
    monkeypatch.setattr(
        wandb.sdk.wandb_login,
        "_verify_login",
        unittest.mock.MagicMock(),
    )


@pytest.fixture
def patch_prompt(monkeypatch):
    monkeypatch.setattr(
        wandb.util, "prompt_choices", lambda x, input_timeout=None, jupyter=False: x[0]
    )
    monkeypatch.setattr(
        wandb.wandb_lib.apikey,
        "prompt_choices",
        lambda x, input_timeout=None, jupyter=False: x[0],
    )


@pytest.fixture
def runner(patch_apikey, patch_prompt):
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
    with unittest.mock.patch.object(
        wandb.sdk.wandb_login,
        "_verify_login",
        return_value=True,
    ):
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
