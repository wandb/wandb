from __future__ import annotations

import sys
import types
from typing import Any, cast

import pytest
import wandb


def _reset_import(monkeypatch, module: str):
    if module in sys.modules:
        monkeypatch.delitem(sys.modules, module, raising=False)


def _inject_fake_weave(monkeypatch):
    m = cast(Any, types.ModuleType("weave"))

    def init(project):
        # no-op stub for weave.init
        return None

    m.init = init
    monkeypatch.setitem(sys.modules, "weave", m)


@pytest.fixture()
def setup_env(monkeypatch, tmp_path):
    monkeypatch.delenv("WANDB_DISABLE_WEAVE", raising=False)
    monkeypatch.setenv("WANDB_MODE", "offline")

    _reset_import(monkeypatch, "weave")


def test_import_nothing(setup_env, mock_wandb_log):
    wandb.init(project="test-project")
    assert not mock_wandb_log.logged("Initializing weave")


def test_import_weave(setup_env, mock_wandb_log, monkeypatch):
    _inject_fake_weave(monkeypatch)
    wandb.init(project="test-project")
    assert mock_wandb_log.logged("Initializing weave")


def test_import_weave_disabled(setup_env, mock_wandb_log, monkeypatch):
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "1")
    _inject_fake_weave(monkeypatch)
    wandb.init(project="test-project")
    assert not mock_wandb_log.logged("Initializing weave")
