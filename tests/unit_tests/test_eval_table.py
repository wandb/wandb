"""Backend-neutral unit tests for wandb.EvalTable."""

from __future__ import annotations

import pytest
import wandb
import wandb.data_types as wandb_data_types
from wandb.errors import UsageError
from wandb.sdk.data_types import eval_table as eval_table_module
from wandb.sdk.data_types.eval_table import UnsupportedMediaMode


@pytest.fixture(autouse=True)
def default_eval_table_server_feature_disabled(monkeypatch):
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table._writer_factory.ServiceApi.feature_enabled",
        lambda self, feature: False,
    )


def test_eval_table_public_imports():
    assert wandb.EvalTable is eval_table_module.EvalTable
    assert wandb_data_types.EvalTable is eval_table_module.EvalTable
    assert UnsupportedMediaMode is eval_table_module.UnsupportedMediaMode


@pytest.mark.parametrize("log_mode", ["MUTABLE", "INCREMENTAL"])
def test_eval_table_only_supports_immutable_log_mode(log_mode):
    with pytest.raises(UsageError, match="only supports log_mode='IMMUTABLE'"):
        wandb.EvalTable(columns=["out"], data=[["x"]], log_mode=log_mode)


def test_eval_table_rejects_unknown_backend():
    with pytest.raises(UsageError, match="Unsupported EvalTable backend"):
        wandb.EvalTable(columns=["x"], backend="unknown")


def test_to_json_requires_bind_for_default_backend(mock_run):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "online"})
    table = wandb.EvalTable(columns=["out"], data=[["x"]])

    with pytest.raises(UsageError, match="must be logged with run.log"):
        table.to_json(run)
