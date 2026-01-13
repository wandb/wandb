from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
import wandb

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
