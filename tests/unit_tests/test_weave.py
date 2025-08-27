from __future__ import annotations

import importlib
import sys

import pytest
import wandb


def _import(module: str):
    """Import a module via importlib to exercise import machinery hooks."""
    return importlib.import_module(module)


def _reset_import(module: str):
    if module in sys.modules:
        del sys.modules[module]


@pytest.fixture()
def setup_env(monkeypatch, tmp_path):
    monkeypatch.delenv("WANDB_DISABLE_WEAVE", raising=False)
    monkeypatch.delenv("WANDB_DISABLE_WEAVE_LLM_INIT", raising=False)
    monkeypatch.setenv("WANDB_MODE", "offline")

    # Create a temporary on-disk weave module so a normal import works
    weave_path = tmp_path / "weave.py"
    weave_path.write_text("# temporary weave module for tests\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    _reset_import("weave")


def test_import_nothing(setup_env, mock_wandb_log):
    wandb.init(project="test-project")
    assert not mock_wandb_log.logged("Initializing weave")


def test_import_weave_before(setup_env, mock_wandb_log):
    _import("weave")
    wandb.init(project="test-project")
    assert mock_wandb_log.logged("Initializing weave")


def test_import_weave_after(setup_env, mock_wandb_log):
    wandb.init(project="test-project")
    _import("weave")
    assert mock_wandb_log.logged("Initializing weave")


def test_disable_weave_import_weave_before(setup_env, mock_wandb_log, monkeypatch):
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "1")
    _import("weave")
    wandb.init(project="test-project")
    assert not mock_wandb_log.logged("Initializing weave")


def test_disable_weave_import_weave_after(setup_env, mock_wandb_log, monkeypatch):
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "1")
    wandb.init(project="test-project")
    _import("weave")
    assert not mock_wandb_log.logged("Initializing weave")
