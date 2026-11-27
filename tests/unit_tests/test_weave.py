from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.integration.weave.weave as wandb_weave_integration
from wandb.errors import UsageError

from tests.fixtures.mock_wandb_log import MockWandbLog


@pytest.fixture()
def fake_weave_init(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake_init = MagicMock()
    monkeypatch.setattr("wandb.integration.weave.weave._weave_init", fake_init)
    return fake_init


@pytest.fixture()
def weave_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "weave", types.ModuleType("weave"))


@pytest.fixture()
def weave_not_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "weave", raising=False)


def test_not_imported(weave_not_imported, fake_weave_init: MagicMock):
    _ = weave_not_imported

    wandb.init(project="test-project", mode="offline")

    fake_weave_init.assert_not_called()


def test_import_weave(
    weave_imported,
    fake_weave_init: MagicMock,
    mock_wandb_log: MockWandbLog,
):
    _ = weave_imported

    wandb.init(project="test-project", mode="offline")

    fake_weave_init.assert_called_once()
    mock_wandb_log.assert_logged("Initializing weave")


def test_import_weave_disabled(
    weave_imported,
    fake_weave_init: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = weave_imported
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "1")

    wandb.init(project="test-project", mode="offline")

    fake_weave_init.assert_not_called()


def test_import_weave_not_disabled_by_false(
    weave_imported,
    fake_weave_init: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    _ = weave_imported
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "false")

    wandb.init(project="test-project", mode="offline")

    fake_weave_init.assert_called_once()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("FALSE", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_is_weave_disabled_parses_boolean_env(
    value: str,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", value)

    assert wandb_weave_integration._is_weave_disabled() is expected


def test_ensure_version_uses_default_missing_weave_message(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setitem(sys.modules, "weave", None)

    with pytest.raises(ImportError, match="weave>=1.2.3 required"):
        wandb_weave_integration.ensure_version("1.2.3")


def test_ensure_version_uses_custom_missing_weave_message(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setitem(sys.modules, "weave", None)

    with pytest.raises(ImportError, match="custom weave message"):
        wandb_weave_integration.ensure_version("1.2.3", "custom weave message")


def test_ensure_version_uses_custom_missing_version_message(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setitem(sys.modules, "weave", types.ModuleType("weave"))

    with pytest.raises(ImportError, match="custom weave message"):
        wandb_weave_integration.ensure_version("1.2.3", "custom weave message")


def test_ensure_version_uses_default_old_weave_message(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_weave = types.ModuleType("weave")
    fake_weave.__version__ = "1.0.0"
    monkeypatch.setitem(sys.modules, "weave", fake_weave)

    with pytest.raises(ImportError, match="weave>=1.2.3 required; found weave==1.0.0"):
        wandb_weave_integration.ensure_version("1.2.3")


def test_ensure_version_uses_custom_old_weave_message(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_weave = types.ModuleType("weave")
    fake_weave.__version__ = "1.0.0"
    monkeypatch.setitem(sys.modules, "weave", fake_weave)

    with pytest.raises(ImportError, match="custom weave message; found weave==1.0.0"):
        wandb_weave_integration.ensure_version("1.2.3", "custom weave message")


def test_init_weave_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock()
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "1")

    with pytest.raises(UsageError, match="WANDB_DISABLE_WEAVE"):
        wandb_weave_integration.init_weave("test-entity", "test-project")

    weave_init.assert_not_called()


def test_init_weave_without_project_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock()
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)

    with pytest.raises(UsageError, match="requires a project"):
        wandb_weave_integration.init_weave("test-entity", None)
    weave_init.assert_not_called()


def test_init_weave_initializes_project(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock()
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)

    wandb_weave_integration.init_weave("test-entity", "test-project")

    weave_init.assert_called_once_with("test-entity/test-project")


def test_init_weave_passes_through_weave_init_import_error(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock(side_effect=ModuleNotFoundError("No module named 'weave'"))
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)

    with pytest.raises(ModuleNotFoundError, match="No module named 'weave'"):
        wandb_weave_integration.init_weave("test-entity", "test-project")


def test_weave_init_skips_matching_active_client(monkeypatch: pytest.MonkeyPatch):
    fake_weave = types.ModuleType("weave")
    fake_weave.__version__ = "999.0.0"
    fake_weave.init = MagicMock()
    fake_weave.get_client = MagicMock(
        return_value=types.SimpleNamespace(
            entity="test-entity",
            project="test-project",
            ensure_project_exists=True,
        )
    )
    monkeypatch.setitem(sys.modules, "weave", fake_weave)

    wandb_weave_integration._weave_init("test-entity/test-project")

    fake_weave.get_client.assert_called_once_with()
    fake_weave.init.assert_not_called()


def test_weave_init_ensure_project_exists_false(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_weave = types.ModuleType("weave")
    fake_weave.__version__ = "999.0.0"
    fake_weave.init = MagicMock()
    fake_weave.get_client = MagicMock(
        return_value=types.SimpleNamespace(
            entity="test-entity",
            project="test-project",
            ensure_project_exists=False,
        )
    )
    monkeypatch.setitem(sys.modules, "weave", fake_weave)

    wandb_weave_integration._weave_init("test-entity/test-project")

    # If weave client flag ensure_project_exists is false, reinit even when active
    # client matches.
    fake_weave.get_client.assert_called_once_with()
    fake_weave.init.assert_called_once_with("test-entity/test-project")


def test_weave_init_rejects_different_active_client(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_weave = types.ModuleType("weave")
    fake_weave.__version__ = "999.0.0"
    fake_weave.init = MagicMock()
    fake_weave.get_client = MagicMock(
        return_value=types.SimpleNamespace(
            entity="old-entity",
            project="old-project",
            ensure_project_exists=True,
        )
    )
    monkeypatch.setitem(sys.modules, "weave", fake_weave)

    with pytest.raises(UsageError, match="already initialized"):
        wandb_weave_integration._weave_init("new-entity/new-project")

    fake_weave.get_client.assert_called_once_with()
    fake_weave.init.assert_not_called()
