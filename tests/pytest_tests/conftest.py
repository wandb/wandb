import os
import shutil
import unittest.mock
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Generator, Iterable, Optional, Union

os.environ["WANDB_ERROR_REPORTING"] = "false"

import git  # noqa: E402
import pytest  # noqa: E402
import wandb  # noqa: E402
import wandb.old.settings  # noqa: E402
import wandb.sdk.lib.apikey  # noqa: E402
import wandb.util  # noqa: E402
from click.testing import CliRunner  # noqa: E402
from wandb import Api  # noqa: E402
from wandb.sdk.interface.interface_queue import InterfaceQueue  # noqa: E402
from wandb.sdk.lib import filesystem, runid  # noqa: E402
from wandb.sdk.lib.gitlib import GitRepo  # noqa: E402
from wandb.sdk.lib.paths import StrPath  # noqa: E402

# --------------------------------
# Misc Fixtures utilities
# --------------------------------


@pytest.fixture(scope="session")
def assets_path() -> Generator[Callable, None, None]:
    def assets_path_fn(path: Path) -> Path:
        return Path(__file__).resolve().parent / "assets" / path

    yield assets_path_fn


@pytest.fixture
def copy_asset(assets_path) -> Generator[Callable, None, None]:
    def copy_asset_fn(path: StrPath, dst: Optional[StrPath] = None) -> Path:
        src = assets_path(path)
        if src.is_file():
            return shutil.copy(src, dst or path)
        return shutil.copytree(src, dst or path)

    yield copy_asset_fn


# --------------------------------
# Misc Fixtures
# --------------------------------


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


@pytest.fixture(scope="function", autouse=True)
def filesystem_isolate(tmp_path):
    kwargs = dict(temp_dir=tmp_path)
    with CliRunner().isolated_filesystem(**kwargs):
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
def dummy_api_key():
    return "1824812581259009ca9981580f8f8a9012409eee"


@pytest.fixture
def patch_apikey(dummy_api_key):
    with unittest.mock.patch.object(
        wandb.sdk.lib.apikey, "isatty", return_value=True
    ), unittest.mock.patch.object(
        wandb.sdk.lib.apikey, "input", return_value=1
    ), unittest.mock.patch.object(
        wandb.sdk.lib.apikey, "getpass", return_value=dummy_api_key
    ):
        yield


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
def api():
    return Api()


# --------------------------------
# Fixtures for user test point
# --------------------------------


@pytest.fixture()
def record_q() -> "Queue":
    return Queue()


@pytest.fixture()
def mocked_interface(record_q: "Queue") -> InterfaceQueue:
    return InterfaceQueue(record_q=record_q)


@pytest.fixture
def mocked_backend(mocked_interface: InterfaceQueue) -> Generator[object, None, None]:
    class MockedBackend:
        def __init__(self) -> None:
            self.interface = mocked_interface

    yield MockedBackend()


def dict_factory():
    def helper():
        return dict()

    return helper


@pytest.fixture(scope="function")
def test_settings():
    def update_test_settings(
        extra_settings: Union[dict, wandb.sdk.wandb_settings.Settings] = dict_factory(),  # noqa: B008
    ):
        settings = wandb.Settings(
            console="off",
            save_code=False,
        )
        if isinstance(extra_settings, dict):
            settings.update(extra_settings, source=wandb.sdk.wandb_settings.Source.BASE)
        elif isinstance(extra_settings, wandb.sdk.wandb_settings.Settings):
            settings.update(extra_settings)
        settings._set_run_start_time()
        return settings

    yield update_test_settings


@pytest.fixture(scope="function")
def mock_run(test_settings, mocked_backend) -> Generator[Callable, None, None]:
    from wandb.sdk.lib.module import unset_globals

    def mock_run_fn(use_magic_mock=False, **kwargs: Any) -> "wandb.sdk.wandb_run.Run":
        kwargs_settings = kwargs.pop("settings", dict())
        kwargs_settings = {
            **{
                "run_id": runid.generate_id(),
            },
            **kwargs_settings,
        }
        run = wandb.wandb_sdk.wandb_run.Run(
            settings=test_settings(kwargs_settings), **kwargs
        )
        run._set_backend(
            unittest.mock.MagicMock() if use_magic_mock else mocked_backend
        )
        run._set_globals()
        return run

    yield mock_run_fn
    unset_globals()


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
