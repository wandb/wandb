"""Backend-neutral unit tests for wandb.EvalTable."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import wandb
import wandb.data_types as wandb_data_types
from wandb.errors import UsageError
from wandb.sdk.data_types import eval_table as eval_table_module
from wandb.sdk.data_types.eval_table import UnsupportedMediaMode
from wandb.sdk.data_types.eval_table._writer import WriteResult


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


def test_to_json_requires_bind(mock_run):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "online"})
    table = wandb.EvalTable(columns=["out"], data=[["x"]], backend="ces")

    with pytest.raises(UsageError, match="must be logged with run.log"):
        table.to_json(run)


@pytest.mark.parametrize(
    "backends, expected_weave, expected_ces",
    [
        ([], False, False),
        ([None], True, False),
        (["weave"], True, False),
        (["ces"], False, True),
        (["weave", "ces"], True, True),
        (["ces", "weave"], True, True),
    ],
)
def test_eval_table_records_backend_telemetry(
    backends, expected_weave, expected_ces, mock_run, monkeypatch
):
    writer = MagicMock()
    writer.write.return_value = WriteResult(history_value={}, logged_id="eval-1")
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.eval_table.create_writer",
        lambda *args, **kwargs: writer,
    )
    monkeypatch.setattr(
        "wandb.apis.public.service_api.ServiceApi.feature_enabled",
        lambda self, feature: True,
    )
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "online"})

    for index, backend in enumerate(backends):
        table = wandb.EvalTable(columns=["output"], data=[["x"]], backend=backend)
        run.log({f"eval_{index}": table})

    assert run._telemetry_obj.feature.eval_table is bool(backends)
    assert run._telemetry_obj.feature.eval_table_weave is expected_weave
    assert run._telemetry_obj.feature.eval_table_ces is expected_ces
