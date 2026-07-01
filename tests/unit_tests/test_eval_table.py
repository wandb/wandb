"""Unit tests for wandb.EvalTable."""

from __future__ import annotations

import datetime
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
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
        lambda entity, project: None,
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
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
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
        @classmethod
        def _create_with_meta(cls, *args, **kwargs):
            order.append("create_with_meta")
            logger = MagicMock()
            logger._evaluate_call.id = "eval-1"
            return logger

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

    assert et.to_json(run)["evaluate_call_id"] == "eval-1"
    assert order == ["init", "evaluation_logger_import", "create_with_meta"]


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
            raise UsageError(
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


# Standard case: 6 columns, 2 each of input/output/score; second log no-op.
def test_standard_immutable_log(mock_eval_logger, mock_wandb_log, run, monkeypatch):
    init_weave = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
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
    ev.log_summary.assert_called_once_with()
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
        "wandb.sdk.data_types.eval_table.weave_integration.init_weave",
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


def test_int_columns_match_role_columns_as_strings(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=[1, 2, 3],
        data=[["in-val", "out-val", 0.9]],
        input_columns=["1"],
        output_columns=["2"],
        score_columns=["3"],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"1": "in-val"},
        output={"2": "out-val"},
        scores={"3": 0.9},
    )


def test_int_columns_default_to_string_output_columns(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=[1, 2],
        data=[["x", 1]],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"row": 1},
        output={"1": "x", "2": 1},
        scores={},
    )


@pytest.mark.usefixtures("mock_eval_logger")
def test_stringified_duplicate_columns_raise(run):
    et = wandb.EvalTable(
        columns=[1, "1"],
        data=[["x", "y"]],
    )

    with pytest.raises(ValueError, match="unique after converting to strings"):
        run.log({"my_eval": et})


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


def test_dataframe_numpy_values_normalized_for_weave(
    mock_eval_logger, run, monkeypatch
):
    np = pytest.importorskip("numpy")
    df = _fake_dataframe(
        monkeypatch,
        columns=["in", "out", "score"],
        rows=[[np.int64(1), np.float64(np.nan), np.bool_(True)]],
    )
    et = wandb.EvalTable(
        dataframe=df,
        input_columns=["in"],
        output_columns=["out"],
        score_columns=["score"],
    )

    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"in": 1},
        output={"out": None},
        scores={"score": True},
    )


def test_numpy_array_values_normalized_for_weave(mock_eval_logger, run):
    np = pytest.importorskip("numpy")
    array_value = np.arange(40)
    et = wandb.EvalTable(
        columns=["array_value"],
        data=[[array_value]],
        input_columns=["array_value"],
    )

    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"array_value": list(range(40))},
        output=None,
        scores={},
    )


def test_python_datetime_values_preserved_for_weave(mock_eval_logger, run):
    py_datetime = datetime.datetime(
        2024,
        1,
        2,
        3,
        4,
        5,
        tzinfo=datetime.timezone.utc,
    )
    py_date = datetime.date(2024, 1, 3)
    py_date_as_datetime = datetime.datetime(
        2024,
        1,
        3,
        tzinfo=datetime.timezone.utc,
    )
    et = wandb.EvalTable(
        columns=["py_datetime", "py_date"],
        data=[[py_datetime, py_date]],
        input_columns=["py_datetime", "py_date"],
    )

    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={
            "py_datetime": py_datetime,
            "py_date": py_date_as_datetime,
        },
        output=None,
        scores={},
    )


def test_numpy_datetime_values_preserved_for_weave(mock_eval_logger, run):
    np = pytest.importorskip("numpy")
    py_datetime = datetime.datetime(
        2024,
        1,
        2,
        3,
        4,
        5,
        tzinfo=datetime.timezone.utc,
    )
    py_date_as_datetime = datetime.datetime(
        2024,
        1,
        3,
        tzinfo=datetime.timezone.utc,
    )
    np_datetime = np.datetime64("2024-01-02T03:04:05.000000000")
    np_date = np.datetime64("2024-01-03")
    np_picosecond_datetime = np.datetime64(
        "1970-01-01T00:00:00.123456789123",
        "ps",
    )
    np_picosecond_datetime_as_datetime = datetime.datetime(
        1970,
        1,
        1,
        0,
        0,
        0,
        123456,
        tzinfo=datetime.timezone.utc,
    )
    np_nat = np.datetime64("NaT")
    et = wandb.EvalTable(
        columns=[
            "np_datetime",
            "np_date",
            "np_picosecond_datetime",
            "np_nat",
        ],
        data=[[np_datetime, np_date, np_picosecond_datetime, np_nat]],
        input_columns=[
            "np_datetime",
            "np_date",
            "np_picosecond_datetime",
            "np_nat",
        ],
    )

    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={
            "np_datetime": py_datetime,
            "np_date": py_date_as_datetime,
            "np_picosecond_datetime": np_picosecond_datetime_as_datetime,
            "np_nat": None,
        },
        output=None,
        scores={},
    )


def test_list_dict_and_tuple_values_normalized_for_weave(mock_eval_logger, run):
    et = wandb.EvalTable(
        columns=["list_value", "dict_value", "tuple_value"],
        data=[
            [
                [1, 2],
                {"values": [3, 4]},
                ("a", "b"),
            ]
        ],
        input_columns=["list_value", "dict_value", "tuple_value"],
    )

    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={
            "list_value": [1, 2],
            "dict_value": {"values": [3, 4]},
            "tuple_value": ["a", "b"],
        },
        output=None,
        scores={},
    )


def test_wandb_media_in_dict_unwrapped_on_log(
    mock_eval_logger,
    mock_wandb_log,
    run,
):
    from PIL import Image as PILImage

    image = wandb.Image(PILImage.new("RGB", (2, 2), color="red"))
    et = wandb.EvalTable(
        columns=["metadata"],
        data=[[{"image": image, "label": "sample"}]],
        input_columns=["metadata"],
    )

    run.log({"my_eval": et})

    mock_wandb_log.assert_warned("wandb.Image values")
    ev = mock_eval_logger.created_loggers[0]
    inputs = ev.log_example.call_args.kwargs["inputs"]
    assert inputs["metadata"]["label"] == "sample"
    assert isinstance(inputs["metadata"]["image"], PILImage.Image)
    assert inputs["metadata"]["image"].size == (2, 2)


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


def test_duplicate_role_columns_warn(mock_eval_logger, mock_wandb_log, run):
    et = wandb.EvalTable(
        columns=["shared", "score"],
        data=[["x", 0.9]],
        input_columns=["shared"],
        output_columns=["shared"],
        score_columns=["score"],
    )

    run.log({"my_eval": et})
    mock_wandb_log.assert_warned("appears in more than one role list")

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
def test_unsupported_wandb_media_cell_raises_in_raise_mode():
    html = wandb.Html("<p>hi</p>")

    with pytest.raises(TypeError) as exc_info:
        wandb.EvalTable(
            columns=["html"],
            data=[[html]],
            unsupported_media_mode="raise",
        )
    assert "unsupported wandb media type 'Html'" in str(exc_info.value)
    assert "unsupported_media_mode='stub'" in str(exc_info.value)


@pytest.mark.usefixtures("mock_eval_logger")
def test_add_data_unsupported_wandb_value_cell_raises_in_raise_mode():
    histogram = wandb.Histogram([1, 2, 3])
    et = wandb.EvalTable(columns=["histogram"], unsupported_media_mode="raise")

    with pytest.raises(TypeError) as exc_info:
        et.add_data(histogram)
    assert "unsupported wandb value type 'Histogram'" in str(exc_info.value)
    assert "unsupported_media_mode='stub'" in str(exc_info.value)

    assert et.data == []


@pytest.mark.usefixtures("mock_eval_logger")
def test_unsupported_media_mode_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unsupported_media_mode"):
        wandb.EvalTable(columns=["x"], unsupported_media_mode="ignore")


def test_unsupported_wandb_media_stubbed_on_log(
    mock_eval_logger,
    mock_wandb_log,
    run,
):
    html = wandb.Html("<p>hi</p>", inject=False)

    et = wandb.EvalTable(
        columns=["html", "label"],
        data=[[html, "ok"]],
        input_columns=["html"],
        output_columns=["label"],
    )

    run.log({"my_eval": et})
    mock_wandb_log.assert_warned("wandb.Html values are not yet supported")

    ev = mock_eval_logger.created_loggers[0]
    inputs = ev.log_example.call_args.kwargs["inputs"]
    stub = inputs["html"]
    assert stub == "[wandb.Html not yet supported]"
    ev.log_example.assert_called_once_with(
        inputs={"html": stub},
        output={"label": "ok"},
        scores={},
    )


def test_external_image_reference_stubbed_on_log(
    mock_eval_logger,
    mock_wandb_log,
    run,
):
    image = wandb.Image("https://example.com/image.png")

    et = wandb.EvalTable(
        columns=["img", "label"],
        data=[[image, "ok"]],
        input_columns=["img"],
        output_columns=["label"],
    )

    run.log({"my_eval": et})
    mock_wandb_log.assert_warned(
        "External media references for wandb.Image are not yet supported"
    )

    ev = mock_eval_logger.created_loggers[0]
    inputs = ev.log_example.call_args.kwargs["inputs"]
    stub = inputs["img"]
    assert stub == "[wandb.Image external reference not yet supported]"
    ev.log_example.assert_called_once_with(
        inputs={"img": stub},
        output={"label": "ok"},
        scores={},
    )


def test_unsupported_wandb_value_without_natural_hash_stubbed_on_log(
    mock_eval_logger,
    mock_wandb_log,
    run,
):
    histogram = wandb.Histogram([1, 2, 3])
    et = wandb.EvalTable(
        columns=["histogram"],
        data=[[histogram]],
    )

    run.log({"my_eval": et})
    mock_wandb_log.assert_warned("wandb.Histogram values are not yet supported")

    ev = mock_eval_logger.created_loggers[0]
    output = ev.log_example.call_args.kwargs["output"]
    stub = output["histogram"]
    assert stub == "[wandb.Histogram not yet supported]"


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


def test_wandb_image_with_int_column_unwrapped_to_pil(mock_eval_logger, run):
    from PIL import Image as PILImage

    pil_in = PILImage.new("RGB", (2, 2), color="red")
    wb_img = wandb.Image(pil_in)

    et = wandb.EvalTable(
        columns=[1],
        data=[[wb_img]],
    )
    run.log({"my_eval": et})

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once()
    call_kwargs = ev.log_example.call_args.kwargs

    output = call_kwargs["output"]
    assert isinstance(output, dict)
    assert set(output) == {"1"}
    assert isinstance(output["1"], PILImage.Image)
    assert output["1"].size == (2, 2)
    assert call_kwargs["inputs"] == {"row": 1}
