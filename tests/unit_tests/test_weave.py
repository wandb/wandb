from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.integration.weave.weave as wandb_weave_integration

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


def test_import_weave_translates_missing_weave(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setitem(sys.modules, "weave", None)

    with pytest.raises(ImportError, match="weave is not installed"):
        wandb_weave_integration.import_weave()


def test_init_weave_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock()
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "1")

    assert wandb_weave_integration.init_weave("test-entity", "test-project") is False
    weave_init.assert_not_called()


def test_init_weave_without_project_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock()
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)

    with pytest.raises(ValueError, match="requires a project"):
        wandb_weave_integration.init_weave("test-entity", None)
    weave_init.assert_not_called()


def test_init_weave_initializes_project(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock()
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)

    assert wandb_weave_integration.init_weave("test-entity", "test-project") is True
    weave_init.assert_called_once_with("test-entity/test-project")


def test_init_weave_translates_weave_init_missing_weave(
    monkeypatch: pytest.MonkeyPatch,
):
    weave_init = MagicMock(side_effect=ModuleNotFoundError("No module named 'weave'"))
    monkeypatch.setattr(wandb_weave_integration, "_weave_init", weave_init)

    with pytest.raises(ImportError, match="weave is not installed"):
        wandb_weave_integration.init_weave("test-entity", "test-project")


def test_weave_init_skips_matching_active_client(monkeypatch: pytest.MonkeyPatch):
    fake_weave = types.ModuleType("weave")
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


def test_weave_init_reinitializes_when_matching_client_did_not_ensure_project_exists(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_weave = types.ModuleType("weave")
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

    fake_weave.get_client.assert_called_once_with()
    fake_weave.init.assert_called_once_with("test-entity/test-project")


def test_weave_init_rejects_different_active_client(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_weave = types.ModuleType("weave")
    fake_weave.init = MagicMock()
    fake_weave.get_client = MagicMock(
        return_value=types.SimpleNamespace(
            entity="old-entity",
            project="old-project",
            ensure_project_exists=True,
        )
    )
    monkeypatch.setitem(sys.modules, "weave", fake_weave)

    with pytest.raises(ValueError, match="already initialized"):
        wandb_weave_integration._weave_init("new-entity/new-project")

    fake_weave.get_client.assert_called_once_with()
    fake_weave.init.assert_not_called()
