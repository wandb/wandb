"""Unit tests for wandb.EvalTable."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.data_types as wandb_data_types
from wandb.errors import UsageError
from wandb.sdk.data_types import eval_table as eval_table_module


@pytest.fixture
def mock_eval_logger(monkeypatch):
    """Mock weave's EvaluationLogger."""
    mock_evaluation_logger_cls = MagicMock()
    created_loggers: list[MagicMock] = []

    def _create_with_meta_side_effect(*args, **kwargs):
        logger = MagicMock()
        logger._evaluate_call.id = f"eval-{len(created_loggers) + 1}"
        logger._init_args = args
        logger._init_kwargs = kwargs
        created_loggers.append(logger)
        return logger

    mock_evaluation_logger_cls._create_with_meta.side_effect = (
        _create_with_meta_side_effect
    )
    mock_evaluation_logger_cls.created_loggers = created_loggers

    weave_module = types.ModuleType("weave")
    weave_module.__path__ = []
    weave_module.__version__ = "999.0.0"
    evaluation_module = types.ModuleType("weave.evaluation")
    evaluation_module.__path__ = []
    eval_imperative_module = types.ModuleType("weave.evaluation.eval_imperative")
    eval_imperative_module.EvaluationLogger = mock_evaluation_logger_cls
    weave_module.evaluation = evaluation_module
    evaluation_module.eval_imperative = eval_imperative_module

    monkeypatch.setitem(sys.modules, "weave", weave_module)
    monkeypatch.setitem(sys.modules, "weave.evaluation", evaluation_module)
    monkeypatch.setitem(
        sys.modules,
        "weave.evaluation.eval_imperative",
        eval_imperative_module,
    )
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table._init_weave_for_run",
        lambda run: None,
    )
    return mock_evaluation_logger_cls


@pytest.fixture
def run(mock_run):
    return mock_run(settings={"entity": "e", "project": "p", "mode": "online"})


def _install_fake_weave(monkeypatch, **attrs):
    module = types.ModuleType("weave")
    module.__path__ = []
    module.__version__ = "999.0.0"
    for name, value in attrs.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, "weave", module)
    return module


def test_eval_table_public_imports():
    assert wandb.EvalTable is eval_table_module.EvalTable
    assert wandb_data_types.EvalTable is eval_table_module.EvalTable


def test_eval_table_offline_run_fails_fast(monkeypatch, mock_eval_logger, mock_run):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "offline"})
    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    init_weave_for_run = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table._init_weave_for_run",
        init_weave_for_run,
    )

    with pytest.raises(UsageError, match="offline mode"):
        run.log({"my_eval": et})

    init_weave_for_run.assert_not_called()
    mock_eval_logger._create_with_meta.assert_not_called()


def test_eval_table_rewrites_weave_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "weave", None)

    with pytest.raises(ImportError) as exc_info:
        wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    message = str(exc_info.value)
    assert "EvalTable dependency error" in message
    assert "pip install" in message
    assert isinstance(exc_info.value.__cause__, ModuleNotFoundError)


def test_eval_table_disabled_weave_raises(monkeypatch, mock_run):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "online"})
    _install_fake_weave(monkeypatch, __version__="999.0.0")
    monkeypatch.setenv("WANDB_DISABLE_WEAVE", "1")

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    with pytest.raises(UsageError, match="WANDB_DISABLE_WEAVE"):
        run.log({"my_eval": et})


def test_eval_table_imports_evaluation_logger_after_weave_init(monkeypatch, run):
    for module_name in (
        "weave",
        "weave.evaluation",
        "weave.evaluation.eval_imperative",
    ):
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    order = []

    class FakeEvaluationLogger:
        _create_with_meta = MagicMock()

    class FakeEvalImperativeModule(types.ModuleType):
        def __getattr__(self, name):
            if name == "EvaluationLogger":
                order.append("evaluation_logger_import")
                return FakeEvaluationLogger
            raise AttributeError(name)

    weave_module = types.ModuleType("weave")
    weave_module.__path__ = []
    weave_module.__version__ = "999.0.0"
    evaluation_module = types.ModuleType("weave.evaluation")
    evaluation_module.__path__ = []
    eval_imperative_module = FakeEvalImperativeModule(
        "weave.evaluation.eval_imperative"
    )
    weave_module.evaluation = evaluation_module
    evaluation_module.eval_imperative = eval_imperative_module
    monkeypatch.setitem(sys.modules, "weave", weave_module)
    monkeypatch.setitem(sys.modules, "weave.evaluation", evaluation_module)
    monkeypatch.setitem(
        sys.modules,
        "weave.evaluation.eval_imperative",
        eval_imperative_module,
    )

    def init_weave(*args, **kwargs):
        order.append("init")

    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
        init_weave,
    )

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    et.bind_to_run(run, "eval", 0)

    with pytest.raises(UsageError, match="not implemented yet"):
        et.to_json(run)

    assert order == ["init", "evaluation_logger_import"]
    FakeEvaluationLogger._create_with_meta.assert_not_called()


def test_eval_table_bind_initializes_weave_for_run(monkeypatch, mock_run):
    _install_fake_weave(monkeypatch)
    init_weave = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
        init_weave,
    )
    run = mock_run(
        settings={"entity": "entity", "project": "project", "mode": "online"}
    )

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    et.bind_to_run(run, "eval", 0)

    init_weave.assert_called_once_with("entity", "project")


def test_eval_table_rejects_rebind_to_different_project(monkeypatch, mock_run):
    _install_fake_weave(monkeypatch)

    def init_weave(entity, project):
        if project == "p2":
            raise ValueError(
                "Weave is already initialized for 'e/p1'; cannot initialize "
                "it for 'e/p2'."
            )

    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
        init_weave,
    )
    run1 = mock_run(settings={"entity": "e", "project": "p1", "mode": "online"})
    run2 = mock_run(settings={"entity": "e", "project": "p2", "mode": "online"})

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    et.bind_to_run(run1, "eval", 0)

    with pytest.raises(UsageError, match="already initialized"):
        et.bind_to_run(run2, "eval", 0)


def test_eval_table_version_mismatch_error_includes_actual_version(monkeypatch):
    monkeypatch.delitem(sys.modules, "weave", raising=False)
    _install_fake_weave(monkeypatch, __version__="0.1.0")

    with pytest.raises(ImportError) as exc_info:
        wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    message = str(exc_info.value)
    assert message.startswith("EvalTable dependency error")
    assert "found weave==0.1.0" in message


@pytest.mark.parametrize("log_mode", ["MUTABLE", "INCREMENTAL"])
def test_eval_table_only_supports_immutable_log_mode(log_mode):
    with pytest.raises(UsageError, match="only supports log_mode='IMMUTABLE'"):
        wandb.EvalTable(columns=["out"], data=[["x"]], log_mode=log_mode)


def test_to_json_rejects_different_run_after_bind(mock_eval_logger, mock_run, run):
    other_run = mock_run(settings={"entity": "e", "project": "other", "mode": "online"})
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    et.bind_to_run(run, "my_eval", 0)

    with pytest.raises(UsageError, match="different run"):
        et.to_json(other_run)

    mock_eval_logger._create_with_meta.assert_not_called()


@pytest.mark.usefixtures("mock_eval_logger")
def test_artifact_path_raises():
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    fake_artifact = MagicMock(spec=wandb.Artifact)

    with pytest.raises(TypeError, match="cannot be logged to a wandb.Artifact"):
        et.to_json(fake_artifact)


@pytest.mark.usefixtures("mock_eval_logger")
def test_parent_table_rejects_evaltable_cell():
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    parent = wandb.Table(columns=["c1", "c2"], data=[[et, "other"]])
    fake_artifact = MagicMock(spec=wandb.Artifact)

    with pytest.raises(TypeError, match="cannot be logged to a wandb.Artifact"):
        parent.to_json(fake_artifact)
