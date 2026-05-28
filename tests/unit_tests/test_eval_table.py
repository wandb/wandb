"""Unit tests for wandb.EvalTable."""

from __future__ import annotations

import importlib
import sys
import types
from io import BytesIO
from unittest.mock import MagicMock

import pytest
import wandb
import wandb.data_types as wandb_data_types
from wandb.errors import UsageError

eval_table_module = importlib.import_module("wandb.sdk.data_types.eval_table")
wandb.EvalTable = eval_table_module.EvalTable
wandb_data_types.EvalTable = eval_table_module.EvalTable


@pytest.fixture
def mock_eval_logger(monkeypatch):
    """Mock weave's EvaluationLogger.

    Each `_create_with_meta(...)` call records a fresh MagicMock instance into
    `mock_eval_logger.created_loggers` and returns it.
    """
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


def _install_fake_weave_video_handler(monkeypatch):
    ensure_registered = MagicMock()

    weave_module = _install_fake_weave(monkeypatch)
    type_handlers_module = types.ModuleType("weave.type_handlers")
    type_handlers_module.__path__ = []
    video_package = types.ModuleType("weave.type_handlers.Video")
    video_package.__path__ = []
    video_module = types.ModuleType("weave.type_handlers.Video.video")
    video_module._ensure_registered = ensure_registered

    weave_module.type_handlers = type_handlers_module
    type_handlers_module.Video = video_package
    video_package.video = video_module

    monkeypatch.setitem(sys.modules, "weave.type_handlers", type_handlers_module)
    monkeypatch.setitem(sys.modules, "weave.type_handlers.Video", video_package)
    monkeypatch.setitem(sys.modules, "weave.type_handlers.Video.video", video_module)

    return ensure_registered


def test_eval_table_offline_run_fails_fast(mock_eval_logger, mock_run):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "offline"})
    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    with pytest.raises(UsageError, match="offline mode"):
        run.log({"my_eval": et})

    mock_eval_logger._create_with_meta.assert_not_called()


def test_eval_table_rewrites_weave_import_error(monkeypatch):
    import_error = ImportError("weave is not installed")

    def fail_import_weave():
        raise import_error

    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.weave_integration.import_weave",
        fail_import_weave,
    )

    with pytest.raises(ImportError) as exc_info:
        wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    assert str(exc_info.value) == eval_table_module._EVAL_TABLE_WEAVE_DEP_MSG
    assert exc_info.value.__cause__ is import_error


def test_eval_table_disabled_weave_raises(monkeypatch, mock_run):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "online"})
    _install_fake_weave(monkeypatch, __version__="999.0.0")

    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
        lambda *args, **kwargs: False,
    )

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    with pytest.raises(RuntimeError, match="Weave logging is disabled"):
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
        @classmethod
        def _create_with_meta(cls, *args, **kwargs):
            order.append("evaluation_logger")
            logger = MagicMock()
            logger._evaluate_call.id = "eval-1"
            return logger

    weave_module = types.ModuleType("weave")
    weave_module.__path__ = []
    weave_module.__version__ = "999.0.0"
    evaluation_module = types.ModuleType("weave.evaluation")
    evaluation_module.__path__ = []
    eval_imperative_module = types.ModuleType("weave.evaluation.eval_imperative")
    eval_imperative_module.EvaluationLogger = FakeEvaluationLogger
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
        return True

    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
        init_weave,
    )

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    et.bind_to_run(run, "eval", 0)

    assert et.to_json(run)["evaluate_call_id"] == "eval-1"
    assert order == ["init", "evaluation_logger"]


def test_eval_table_bind_initializes_weave_for_run(monkeypatch, mock_run):
    _install_fake_weave(monkeypatch)
    init_weave = MagicMock(return_value=True)
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
        return True

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
    assert f"weave>={eval_table_module._MIN_WEAVE_VERSION}" in message
    assert "found weave==0.1.0" in message


# Standard case: 6 columns, 2 each of input/output/score; second log no-op.
def test_standard_immutable_log(mock_eval_logger, mock_wandb_log, run, monkeypatch):
    init_weave = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table._init_weave_for_run",
        init_weave,
    )

    et = wandb.EvalTable(
        columns=["in1", "in2", "out1", "out2", "score1", "score2"],
        data=[
            ["in1-val", "in2-val", "out1-val", "out2-val", 0.5, 0.7],
            ["in1-val2", "in2-val2", "out1-val2", "out2-val2", 0.6, 0.8],
        ],
        input_columns=["in1", "in2"],
        output_columns=["out1", "out2"],
        score_columns=["score1", "score2"],
    )

    run.log({"my_eval": et})

    mock_eval_logger._create_with_meta.assert_called_once_with(
        {"wandb_eval_table": True},
        name="my_eval",
    )

    ev = mock_eval_logger.created_loggers[0]
    assert ev.log_example.call_count == 2
    ev.log_example.assert_any_call(
        inputs={"in1": "in1-val", "in2": "in2-val"},
        output={"out1": "out1-val", "out2": "out2-val"},
        scores={"score1": 0.5, "score2": 0.7},
    )
    ev.log_example.assert_any_call(
        inputs={"in1": "in1-val2", "in2": "in2-val2"},
        output={"out1": "out1-val2", "out2": "out2-val2"},
        scores={"score1": 0.6, "score2": 0.8},
    )
    ev.log_summary.assert_called_once_with(None, auto_summarize=True)
    assert et._immutable_evaluate_call_id == "eval-1"

    # Second log on IMMUTABLE table is a no-op.
    run.log({"my_eval": et})
    assert mock_eval_logger._create_with_meta.call_count == 1
    assert init_weave.call_count == 1
    assert ev.log_example.call_count == 2
    assert ev.log_summary.call_count == 1
    mock_wandb_log.assert_warned(
        "EvalTable with log_mode='IMMUTABLE' has already been logged"
    )


def test_immutable_mutation_after_log_warns_and_still_noops(
    mock_eval_logger, mock_wandb_log, run
):
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    run.log({"my_eval": et})
    ev = mock_eval_logger.created_loggers[0]

    et.add_data("y")
    run.log({"my_eval": et})

    assert mock_eval_logger._create_with_meta.call_count == 1
    assert ev.log_example.call_count == 1
    ev.log_example.assert_called_once_with(
        inputs={"row": 1},
        output={"out": "x"},
        scores={},
    )
    mock_wandb_log.assert_warned("mutating a Table with log_mode='IMMUTABLE'")
    mock_wandb_log.assert_warned(
        "EvalTable with log_mode='IMMUTABLE' has already been logged"
    )


def test_mutation_after_failed_log_does_not_warn_as_already_logged(
    monkeypatch, mock_wandb_log, mock_run
):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "online"})
    _install_fake_weave(monkeypatch, __version__="999.0.0")

    def fail_init_weave(*args, **kwargs):
        raise ImportError("weave is not installed")

    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table._init_weave_for_run",
        fail_init_weave,
    )

    et = wandb.EvalTable(columns=["out"], data=[["x"]])

    with pytest.raises(ImportError):
        run.log({"my_eval": et})

    et.add_data("y")

    assert not any(
        "mutating a Table with log_mode='IMMUTABLE'" in msg
        for msg in mock_wandb_log._logs(mock_wandb_log._termwarn)
    )


def test_immutable_relog_returns_original_json_after_mutation(
    mock_eval_logger, mock_wandb_log, run
):
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    et.bind_to_run(run, "my_eval", 0)

    first_json = et.to_json(run)

    et.add_data("y")
    second_json = et.to_json(run)

    assert second_json == first_json
    assert second_json["nrows"] == 1
    assert mock_eval_logger._create_with_meta.call_count == 1
    mock_wandb_log.assert_warned("mutating a Table with log_mode='IMMUTABLE'")
    mock_wandb_log.assert_warned(
        "EvalTable with log_mode='IMMUTABLE' has already been logged"
    )


def test_to_json_rejects_different_run_after_first_log(mock_eval_logger, mock_run, run):
    other_run = mock_run(settings={"entity": "e", "project": "other", "mode": "online"})
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    run.log({"my_eval": et})

    with pytest.raises(UsageError, match="different run"):
        et.to_json(other_run)

    assert mock_eval_logger._create_with_meta.call_count == 1


# set_summary with auto_summarize=False.
def test_custom_summary(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=["in", "out"],
        data=[["in-val", "out-val"]],
        input_columns=["in"],
    )
    et.set_summary({"val_loss": 0.3}, auto_summarize=False)
    run.log({"my_eval": et})

    mock_eval_logger._create_with_meta.assert_called_once_with(
        {"wandb_eval_table": True},
        name="my_eval",
    )
    ev = mock_eval_logger.created_loggers[0]
    ev.log_summary.assert_called_once_with({"val_loss": 0.3}, auto_summarize=False)


# No input/output/score categorization: row index injected, all default to output.
def test_no_categorization_injects_row_index(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=["out1", "out2"],
        data=[["x", 1], ["y", 2]],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    assert ev.log_example.call_count == 2
    ev.log_example.assert_any_call(
        inputs={"row": 1},
        output={"out1": "x", "out2": 1},
        scores={},
    )
    ev.log_example.assert_any_call(
        inputs={"row": 2},
        output={"out1": "y", "out2": 2},
        scores={},
    )


# No input columns but score columns: row injected, unspecified default to output.
def test_no_input_with_score_columns(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=["out1", "out2", "score"],
        data=[["x", 1, 0.9]],
        score_columns=["score"],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"row": 1},
        output={"out1": "x", "out2": 1},
        scores={"score": 0.9},
    )


# All columns assigned to input/score roles: no output payload is logged.
def test_no_output_columns_logs_none_output(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=["in", "score"],
        data=[["x", 0.9]],
        input_columns=["in"],
        score_columns=["score"],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"in": "x"},
        output=None,
        scores={"score": 0.9},
    )


# columns=None but role lists provided → columns derived from role lists.
def test_columns_derived_from_role_lists(mock_eval_logger, run):
    et = wandb.EvalTable(
        data=[["in-val", "out-val", 0.5]],
        input_columns=["in"],
        output_columns=["out"],
        score_columns=["score"],
    )
    # Parent Table's columns = input + output + score, in that order.
    assert et.columns == ["in", "out", "score"]

    run.log({"my_eval": et})
    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"in": "in-val"},
        output={"out": "out-val"},
        scores={"score": 0.5},
    )


# Derived columns count mismatched against data: parent Table raises.
@pytest.mark.usefixtures("mock_eval_logger")
def test_derived_columns_count_mismatch_raises():
    # Role lists imply 3 columns; data rows have 4 values.
    with pytest.raises(ValueError):
        wandb.EvalTable(
            data=[[1, 2, 3, 4]],
            input_columns=["in"],
            output_columns=["out"],
            score_columns=["score"],
        )


def _fake_dataframe(monkeypatch, columns, rows):
    class _FakeSeries:
        def __init__(self, values):
            self.values = values

    class FakeDataFrame:
        # `wandb.util.is_pandas_data_frame` falls back to a typename check
        # when pandas isn't importable; it accepts anything whose
        # __module__ starts with "pandas." and whose name contains
        # "DataFrame".
        __module__ = "pandas.core.frame"

        def __init__(self, columns, rows):
            self.columns = columns
            self._rows = rows

        def __getitem__(self, col):
            idx = list(self.columns).index(col)
            return _FakeSeries([row[idx] for row in self._rows])

        def __len__(self):
            return len(self._rows)

    # Force the typename-string fallback so the test is hermetic regardless
    # of whether pandas is installed in the host env.
    monkeypatch.setattr("wandb.util.pd_available", False)

    return FakeDataFrame(columns=columns, rows=rows)


# DataFrame input: parent Table populates columns/data from the frame.
def test_dataframe_input(mock_eval_logger, run, monkeypatch):
    df = _fake_dataframe(
        monkeypatch,
        columns=["in", "out", "score"],
        rows=[["in1", "out1", 0.5], ["in2", "out2", 0.6]],
    )
    et = wandb.EvalTable(
        dataframe=df,
        input_columns=["in"],
        score_columns=["score"],
    )

    # Parent Table read columns straight off the dataframe.
    assert et.columns == ["in", "out", "score"]

    run.log({"my_eval": et})
    ev = mock_eval_logger.created_loggers[0]
    assert ev.log_example.call_count == 2
    # `o` defaults to output (not in any role list), `s` is score, `i` is input.
    ev.log_example.assert_any_call(
        inputs={"in": "in1"}, output={"out": "out1"}, scores={"score": 0.5}
    )
    ev.log_example.assert_any_call(
        inputs={"in": "in2"}, output={"out": "out2"}, scores={"score": 0.6}
    )


@pytest.mark.usefixtures("mock_eval_logger")
def test_dataframe_nested_table_cell_raises(monkeypatch):
    inner = wandb.Table(columns=["x"], data=[["v"]])
    df = _fake_dataframe(monkeypatch, columns=["t", "n"], rows=[[inner, 1]])

    with pytest.raises(TypeError, match="does not support nested Tables"):
        wandb.EvalTable(dataframe=df)


@pytest.mark.parametrize("log_mode", ["MUTABLE", "INCREMENTAL"])
def test_eval_table_only_supports_immutable_log_mode(log_mode):
    with pytest.raises(UsageError, match="only supports log_mode='IMMUTABLE'"):
        wandb.EvalTable(columns=["out"], data=[["x"]], log_mode=log_mode)


# Column-role mismatch: column listed in input/output/score but not in columns.
@pytest.mark.usefixtures("mock_eval_logger")
def test_column_role_mismatch_raises(run):
    et = wandb.EvalTable(
        columns=["out1", "out2"],
        data=[["x", 1]],
        input_columns=["nonexistent"],
    )
    with pytest.raises(ValueError, match="do not exist in the table"):
        run.log({"my_eval": et})


def test_duplicate_role_columns_warn(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=["shared", "score"],
        data=[["x", 0.9]],
        input_columns=["shared"],
        output_columns=["shared"],
        score_columns=["score"],
    )

    with pytest.warns(UserWarning, match="appears in more than one role list"):
        run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"shared": "x"},
        output={"shared": "x"},
        scores={"score": 0.9},
    )


# Nested Table inside an EvalTable cell: rejected at insertion time.
@pytest.mark.usefixtures("mock_eval_logger")
def test_nested_table_cell_raises_from_constructor():
    inner = wandb.Table(columns=["x"], data=[["v"]])

    with pytest.raises(TypeError, match="does not support nested Tables"):
        wandb.EvalTable(columns=["t", "n"], data=[[inner, 1]])


@pytest.mark.usefixtures("mock_eval_logger")
def test_add_data_nested_table_cell_raises():
    inner = wandb.Table(columns=["x"], data=[["v"]])
    et = wandb.EvalTable(columns=["t", "n"])

    with pytest.raises(TypeError, match="does not support nested Tables"):
        et.add_data(inner, 1)

    assert et.data == []


@pytest.mark.usefixtures("mock_eval_logger")
def test_add_column_nested_table_cell_raises():
    inner = wandb.Table(columns=["x"], data=[["v"]])
    et = wandb.EvalTable(columns=["n"], data=[[1]])

    with pytest.raises(TypeError, match="does not support nested Tables"):
        et.add_column("t", [inner])

    assert et.columns == ["n"]
    assert et.data == [[1]]


@pytest.mark.usefixtures("mock_eval_logger")
def test_unsupported_wandb_media_cell_raises_from_constructor():
    html = wandb.Html("<p>hi</p>")

    with pytest.raises(TypeError) as exc_info:
        wandb.EvalTable(columns=["html"], data=[[html]])
    assert "unsupported wandb media type 'Html'" in str(exc_info.value)
    assert "unsupported_media_mode='stub'" in str(exc_info.value)


@pytest.mark.usefixtures("mock_eval_logger")
def test_add_data_unsupported_wandb_value_cell_raises():
    histogram = wandb.Histogram([1, 2, 3])
    et = wandb.EvalTable(columns=["histogram"])

    with pytest.raises(TypeError) as exc_info:
        et.add_data(histogram)
    assert "unsupported wandb value type 'Histogram'" in str(exc_info.value)
    assert "unsupported_media_mode='stub'" in str(exc_info.value)

    assert et.data == []


@pytest.mark.usefixtures("mock_eval_logger")
def test_unsupported_media_mode_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unsupported_media_mode"):
        wandb.EvalTable(columns=["x"], unsupported_media_mode="ignore")


def test_unsupported_wandb_media_stubbed_on_log(mock_eval_logger, run):
    html = wandb.Html("<p>hi</p>", inject=False)
    assert html._sha256 is not None
    expected_stub = f"[wandb.Html unsupported: {html._sha256[:8]}]"

    et = wandb.EvalTable(
        columns=["html", "label"],
        data=[[html, "ok"]],
        input_columns=["html"],
        output_columns=["label"],
        unsupported_media_mode="stub",
    )

    with pytest.warns(UserWarning, match="wandb.Html values are not supported"):
        run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"html": expected_stub},
        output={"label": "ok"},
        scores={},
    )


def test_unsupported_wandb_value_without_natural_hash_stubbed_on_log(
    mock_eval_logger, run
):
    histogram = wandb.Histogram([1, 2, 3])
    et = wandb.EvalTable(
        columns=["histogram"],
        data=[[histogram]],
        unsupported_media_mode="stub",
    )

    with pytest.warns(UserWarning, match="wandb.Histogram values are not supported"):
        run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    output = ev.log_example.call_args.kwargs["output"]
    stub = output["histogram"]
    assert stub.startswith("[wandb.Histogram unsupported: ")
    assert stub.endswith("]")
    digest = stub.removeprefix("[wandb.Histogram unsupported: ").removesuffix("]")
    assert len(digest) == 8


# Logging an EvalTable to an Artifact: rejected.
@pytest.mark.usefixtures("mock_eval_logger")
def test_artifact_path_raises():
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    fake_artifact = MagicMock(spec=wandb.Artifact)

    with pytest.raises(TypeError, match="cannot be logged to a wandb.Artifact"):
        et.to_json(fake_artifact)


# Parent wandb.Table rejects EvalTable cells through artifact serialization.
@pytest.mark.usefixtures("mock_eval_logger")
def test_parent_table_rejects_evaltable_cell():
    et = wandb.EvalTable(columns=["out"], data=[["x"]])
    parent = wandb.Table(columns=["c1", "c2"], data=[[et, "other"]])
    fake_artifact = MagicMock(spec=wandb.Artifact)

    with pytest.raises(TypeError, match="cannot be logged to a wandb.Artifact"):
        parent.to_json(fake_artifact)


# wandb.Image cell values are unwrapped to PIL.Image before being
# passed to log_example, so weave can use its image type handler.
def test_wandb_image_cell_unwrapped_to_pil(mock_eval_logger, run):
    from PIL import Image as PILImage

    pil_in = PILImage.new("RGB", (2, 2), color="red")
    wb_img = wandb.Image(pil_in)

    et = wandb.EvalTable(
        columns=["img"],
        data=[[wb_img]],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once()
    call_kwargs = ev.log_example.call_args.kwargs

    output = call_kwargs["output"]
    # Single-column output is still wrapped in a dict, keyed by column name.
    assert isinstance(output, dict)
    img = output["img"]
    assert isinstance(img, PILImage.Image), (
        f"expected PIL.Image.Image, got {type(img).__name__}"
    )
    # And it's the same image content (round-tripped through wandb.Image).
    assert img.size == (2, 2)
    assert call_kwargs["inputs"] == {"row": 1}


def test_wandb_audio_path_cell_uses_weave_audio_from_path(
    mock_eval_logger, run, monkeypatch, tmp_path
):
    class FakeWeaveAudio:
        calls = []

        @classmethod
        def from_path(cls, path):
            cls.calls.append(("from_path", path))
            return {"kind": "audio-path", "path": path}

        @classmethod
        def from_data(cls, data, format):
            cls.calls.append(("from_data", data, format))
            return {"kind": "audio-data", "data": data, "format": format}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake-wave")

    et = wandb.EvalTable(columns=["audio"], data=[[wandb.Audio(str(audio_path))]])
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    output = ev.log_example.call_args.kwargs["output"]
    assert output["audio"] == {"kind": "audio-path", "path": audio_path}
    assert FakeWeaveAudio.calls == [("from_path", audio_path)]


def test_wandb_audio_data_cell_uses_weave_audio_from_path(
    mock_eval_logger, run, monkeypatch
):
    from wandb.sdk.data_types import audio as audio_module

    class FakeSoundFile:
        @staticmethod
        def write(path, data, sample_rate):
            with open(path, "wb") as f:
                f.write(b"RIFFfake-wave")

    original_get_module = audio_module.util.get_module

    def fake_get_module(name, required=None):
        if name == "soundfile":
            return FakeSoundFile
        return original_get_module(name, required=required)

    class FakeWeaveAudio:
        calls = []

        @classmethod
        def from_path(cls, path):
            cls.calls.append(("from_path", path))
            return {"kind": "audio-path", "path": path}

        @classmethod
        def from_data(cls, data, format):
            cls.calls.append(("from_data", data, format))
            return {"kind": "audio-data", "data": data, "format": format}

    monkeypatch.setattr(audio_module.util, "get_module", fake_get_module)
    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)

    et = wandb.EvalTable(
        columns=["audio"],
        data=[[wandb.Audio([0.0, 0.1], sample_rate=2)]],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    output = ev.log_example.call_args.kwargs["output"]
    assert output["audio"]["kind"] == "audio-path"
    assert output["audio"]["path"].suffix == ".wav"
    assert FakeWeaveAudio.calls == [("from_path", output["audio"]["path"])]


def test_wandb_video_path_cell_uses_moviepy_video_file_clip(
    mock_eval_logger, run, monkeypatch, tmp_path
):
    ensure_video_registered = _install_fake_weave_video_handler(monkeypatch)

    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    class FakeVideoClip:
        pass

    moviepy = types.ModuleType("moviepy")
    editor = types.ModuleType("moviepy.editor")
    editor.VideoClip = FakeVideoClip
    editor.VideoFileClip = FakeVideoFileClip
    monkeypatch.setitem(sys.modules, "moviepy", moviepy)
    monkeypatch.setitem(sys.modules, "moviepy.editor", editor)

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")

    et = wandb.EvalTable(columns=["video"], data=[[wandb.Video(str(video_path))]])
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    output = ev.log_example.call_args.kwargs["output"]
    assert isinstance(output["video"], FakeVideoFileClip)
    assert output["video"].path == str(video_path)
    ensure_video_registered.assert_called_once_with()


def test_wandb_video_path_cell_requires_moviepy_editor(
    mock_eval_logger, run, monkeypatch, tmp_path
):
    _install_fake_weave_video_handler(monkeypatch)

    class FakeVideoFileClip:
        pass

    class FakeVideoClip:
        pass

    moviepy = types.ModuleType("moviepy")
    moviepy.VideoClip = FakeVideoClip
    moviepy.VideoFileClip = FakeVideoFileClip
    monkeypatch.setitem(sys.modules, "moviepy", moviepy)
    monkeypatch.delitem(sys.modules, "moviepy.editor", raising=False)

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-video")

    et = wandb.EvalTable(columns=["video"], data=[[wandb.Video(str(video_path))]])

    with pytest.raises(ImportError, match="moviepy.editor"):
        run.log({"my_eval": et})


def test_wandb_video_bytes_cell_uses_moviepy_video_file_clip(
    mock_eval_logger, run, monkeypatch
):
    ensure_video_registered = _install_fake_weave_video_handler(monkeypatch)

    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    class FakeVideoClip:
        pass

    moviepy = types.ModuleType("moviepy")
    editor = types.ModuleType("moviepy.editor")
    editor.VideoClip = FakeVideoClip
    editor.VideoFileClip = FakeVideoFileClip
    monkeypatch.setitem(sys.modules, "moviepy", moviepy)
    monkeypatch.setitem(sys.modules, "moviepy.editor", editor)

    et = wandb.EvalTable(
        columns=["video"],
        data=[[wandb.Video(BytesIO(b"fake-video"), format="mp4")]],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    output = ev.log_example.call_args.kwargs["output"]
    assert isinstance(output["video"], FakeVideoFileClip)
    assert output["video"].path.endswith(".mp4")
    ensure_video_registered.assert_called_once_with()


def test_wandb_video_data_cell_uses_moviepy_video_file_clip(
    mock_eval_logger, run, monkeypatch
):
    from wandb.sdk.data_types import video as video_module

    ensure_video_registered = _install_fake_weave_video_handler(monkeypatch)

    np = pytest.importorskip("numpy")

    class FakeWandbImageSequenceClip:
        def __init__(self, frames, fps):
            self.frames = frames
            self.fps = fps

        def write_videofile(self, path, logger=None):
            with open(path, "wb") as f:
                f.write(b"fake-encoded-video")

    original_get_module = video_module.util.get_module

    def fake_get_module(name, required=None):
        if name == "moviepy.video.io.ImageSequenceClip":
            return types.SimpleNamespace(ImageSequenceClip=FakeWandbImageSequenceClip)
        return original_get_module(name, required=required)

    class FakeVideoFileClip:
        def __init__(self, path):
            self.path = path

    class FakeVideoClip:
        pass

    monkeypatch.setattr(video_module.util, "get_module", fake_get_module)
    moviepy = types.ModuleType("moviepy")
    editor = types.ModuleType("moviepy.editor")
    editor.VideoClip = FakeVideoClip
    editor.VideoFileClip = FakeVideoFileClip
    monkeypatch.setitem(sys.modules, "moviepy", moviepy)
    monkeypatch.setitem(sys.modules, "moviepy.editor", editor)

    frames = np.zeros((2, 3, 4, 4), dtype=np.uint8)
    et = wandb.EvalTable(
        columns=["video"],
        data=[[wandb.Video(frames, format="mp4", fps=7)]],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    output = ev.log_example.call_args.kwargs["output"]
    assert isinstance(output["video"], FakeVideoFileClip)
    assert output["video"].path.endswith(".mp4")
    ensure_video_registered.assert_called_once_with()


def test_media_adapter_rejects_external_image_reference():
    from wandb.integration.weave.media_adapters import unwrap_value

    image = wandb.Image("https://example.com/image.png")

    with (
        pytest.warns(UserWarning, match="wandb.Image values"),
        pytest.raises(
            TypeError,
            match="Unsupported external media reference",
        ),
    ):
        unwrap_value(image, "img", set())


def test_media_adapter_rejects_external_audio_reference(monkeypatch):
    from wandb.integration.weave.media_adapters import unwrap_value

    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = wandb.Audio("https://example.com/audio.wav")

    with (
        pytest.warns(UserWarning, match="wandb.Audio values"),
        pytest.raises(
            TypeError,
            match="Unsupported external media reference",
        ),
    ):
        unwrap_value(audio, "audio", set())


def test_media_adapter_rejects_media_without_local_path(monkeypatch):
    from wandb.integration.weave.media_adapters import unwrap_value

    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            return {"path": path}

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio = object.__new__(wandb.Audio)
    audio._path = None

    with (
        pytest.warns(UserWarning, match="wandb.Audio values"),
        pytest.raises(
            TypeError,
            match="does not have a local file path",
        ),
    ):
        unwrap_value(audio, "audio", set())


def test_media_adapter_rethrows_weave_audio_value_error(monkeypatch, tmp_path):
    from wandb.integration.weave.media_adapters import unwrap_value

    class FakeWeaveAudio:
        @classmethod
        def from_path(cls, path):
            raise ValueError("unsupported audio")

    _install_fake_weave(monkeypatch, Audio=FakeWeaveAudio)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake-wave")
    audio = wandb.Audio(str(audio_path))

    with (
        pytest.warns(UserWarning, match="wandb.Audio values"),
        pytest.raises(
            TypeError,
            match="Cannot convert wandb.Audio in column 'audio' for Weave logging",
        ),
    ):
        unwrap_value(audio, "audio", set())


def test_media_adapter_rejects_unsupported_wandb_media():
    from wandb.integration.weave.media_adapters import unwrap_value

    html = wandb.Html("<p>hi</p>")

    with pytest.raises(TypeError, match="unsupported wandb media type 'Html'"):
        unwrap_value(html, "html", set())
