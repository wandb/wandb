"""
require user tests.
"""

import pytest
import wandb


@pytest.fixture
def require_mock(mocker):
    cleanup = []

    def fn(require, func):
        cleanup.append(require)
        mocker.patch.object(
            wandb.wandb_sdk.wandb_require._Enables,
            "require_" + require,
            func,
            create=True,
        )

    # TODO(require): Remove below when we are ready to ship
    wandb.require = wandb._require

    yield fn
    for require in cleanup:
        wandb.__dict__.pop("require_" + require, None)

    # TODO(require): Remove below when we are ready to ship
    wandb.__dict__.pop("require", None)


def test_require_single(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something")
    captured = capsys.readouterr()
    assert "unsupported require: something" in captured.err


def test_require_list(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something,another")
    captured = capsys.readouterr()
    assert "unsupported require: something" in captured.err
    assert "unsupported require: another" in captured.err


def test_require_version(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something:beta")
    captured = capsys.readouterr()
    assert "unsupported require: something" in captured.err


def test_require_extra_args(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something:beta", "unsupported")
    captured = capsys.readouterr()
    assert "ignoring unsupported parameter: unsupported" in captured.err


def test_require_extra_kwargs(user_test, capsys):
    with pytest.raises(wandb.errors.RequireError):
        wandb.require("something:beta", junk="unsupported")
    captured = capsys.readouterr()
    assert "ignoring unsupported named parameter: junk" in captured.err


def test_require_good(user_test, require_mock):
    def mock_require_test(self):
        wandb.require_test = lambda x: x + 2

    require_mock("test", mock_require_test)
    wandb.require("test")

    assert wandb.require_test(2) == 4
