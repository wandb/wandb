"""Unit tests for wandb.EvalTable."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import wandb
from wandb.errors import UsageError


@pytest.fixture
def mock_eval_logger(monkeypatch):
    """Mock weave's EvaluationLogger.

    Each `_create_with_meta(...)` call records a fresh MagicMock instance into
    `mock_eval_logger.created_loggers` and returns it.
    """
    mock_cls = MagicMock()
    created_loggers: list[MagicMock] = []

    def _create_with_meta_side_effect(*args, **kwargs):
        logger = MagicMock()
        logger._init_args = args
        logger._init_kwargs = kwargs
        created_loggers.append(logger)
        return logger

    mock_cls._create_with_meta.side_effect = _create_with_meta_side_effect
    mock_cls.created_loggers = created_loggers

    # Capture atexit handlers so they don't leak between tests AND so tests
    # can fire them on demand (e.g. to verify INCREMENTAL summary timing).
    atexit_handlers: list = []
    mock_cls.atexit_handlers = atexit_handlers

    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table._import_evaluation_logger",
        lambda: mock_cls,
    )
    monkeypatch.setattr(
        "wandb.integration.weave.weave.setup_with_import",
        lambda *a, **kw: True,
    )
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table.atexit.register",
        lambda fn: (atexit_handlers.append(fn), fn)[1],
    )
    return mock_cls


@pytest.fixture
def mock_run():
    return MagicMock(entity="e", project="p")


def _log(et, run, key="my_eval", step=0):
    """Helper: run the framework's bind-then-to_json sequence."""
    et.bind_to_run(run, key, step=step)
    et.to_json(run)


# Standard case: 6 columns, 2 each of input/output/score; second log no-op.
def test_standard_immutable_log(mock_eval_logger, mock_run, monkeypatch):
    termwarn = MagicMock()
    monkeypatch.setattr(wandb, "termwarn", termwarn)

    et = wandb.EvalTable(
        columns=["i1", "i2", "o1", "o2", "s1", "s2"],
        data=[
            ["i1-v", "i2-v", "o1-v", "o2-v", 0.5, 0.7],
            ["i1-v2", "i2-v2", "o1-v2", "o2-v2", 0.6, 0.8],
        ],
        input_columns=["i1", "i2"],
        output_columns=["o1", "o2"],
        score_columns=["s1", "s2"],
    )
    _log(et, mock_run)

    mock_eval_logger._create_with_meta.assert_called_once_with(
        {"wandb_eval_table": True},
        name="my_eval",
        dataset=[
            {"i1": "i1-v", "i2": "i2-v"},
            {"i1": "i1-v2", "i2": "i2-v2"},
        ],
    )

    ev = mock_eval_logger.created_loggers[0]
    assert ev.log_example.call_count == 2
    ev.log_example.assert_any_call(
        inputs={"i1": "i1-v", "i2": "i2-v"},
        output={"o1": "o1-v", "o2": "o2-v"},
        scores={"s1": 0.5, "s2": 0.7},
    )
    ev.log_example.assert_any_call(
        inputs={"i1": "i1-v2", "i2": "i2-v2"},
        output={"o1": "o1-v2", "o2": "o2-v2"},
        scores={"s1": 0.6, "s2": 0.8},
    )
    ev.log_summary.assert_called_once_with(None, auto_summarize=True)
    assert mock_eval_logger.atexit_handlers == []

    # Second log on IMMUTABLE table is a no-op.
    et.to_json(mock_run)
    assert mock_eval_logger._create_with_meta.call_count == 1
    assert ev.log_example.call_count == 2
    assert ev.log_summary.call_count == 1
    termwarn.assert_called_once_with(
        "EvalTable with log_mode='IMMUTABLE' has already been logged. "
        "Subsequent run.log() calls have no effect. Set "
        "log_mode='MUTABLE' or log_mode='INCREMENTAL' to log updates.",
        repeat=False,
    )


# set_summary with auto_summarize=False.
def test_custom_summary(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        columns=["i", "o"],
        data=[["i-v", "o-v"]],
        input_columns=["i"],
    )
    et.set_summary({"val_loss": 0.3}, auto_summarize=False)
    _log(et, mock_run)

    mock_eval_logger._create_with_meta.assert_called_once_with(
        {"wandb_eval_table": True},
        name="my_eval",
        dataset=[{"i": "i-v"}],
    )
    ev = mock_eval_logger.created_loggers[0]
    ev.log_summary.assert_called_once_with({"val_loss": 0.3}, auto_summarize=False)


# No input/output/score categorization: row index injected, all default to output.
def test_no_categorization_injects_row_index(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        columns=["o1", "o2"],
        data=[["x", 1], ["y", 2]],
    )
    _log(et, mock_run)

    ev = mock_eval_logger.created_loggers[0]
    assert ev.log_example.call_count == 2
    ev.log_example.assert_any_call(
        inputs={"row": 1},
        output={"o1": "x", "o2": 1},
        scores={},
    )
    ev.log_example.assert_any_call(
        inputs={"row": 2},
        output={"o1": "y", "o2": 2},
        scores={},
    )


# No input columns but score columns: row injected, unspecified default to output.
def test_no_input_with_score_columns(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        columns=["o1", "o2", "s"],
        data=[["x", 1, 0.9]],
        score_columns=["s"],
    )
    _log(et, mock_run)

    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"row": 1},
        output={"o1": "x", "o2": 1},
        scores={"s": 0.9},
    )


# columns=None but role lists provided → columns derived from role lists.
def test_columns_derived_from_role_lists(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        data=[["i-v", "o-v", 0.5]],
        input_columns=["i"],
        output_columns=["o"],
        score_columns=["s"],
    )
    # Parent Table's columns = input + output + score, in that order.
    assert et.columns == ["i", "o", "s"]

    _log(et, mock_run)
    ev = mock_eval_logger.created_loggers[0]
    ev.log_example.assert_called_once_with(
        inputs={"i": "i-v"},
        output={"o": "o-v"},
        scores={"s": 0.5},
    )


# Derived columns count mismatched against data: parent Table raises.
@pytest.mark.usefixtures("mock_eval_logger")
def test_derived_columns_count_mismatch_raises():
    # Role lists imply 3 columns; data rows have 4 values.
    with pytest.raises(ValueError):
        wandb.EvalTable(
            data=[[1, 2, 3, 4]],
            input_columns=["i"],
            output_columns=["o"],
            score_columns=["s"],
        )


# DataFrame input: parent Table populates columns/data from the frame.
# Uses a duck-typed fake (no pandas dep) by spoofing the module path so
# wandb's `is_pandas_data_frame` typename check accepts it.
def test_dataframe_input(mock_eval_logger, mock_run, monkeypatch):
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

    df = FakeDataFrame(
        columns=["i", "o", "s"],
        rows=[["i1", "o1", 0.5], ["i2", "o2", 0.6]],
    )
    et = wandb.EvalTable(
        dataframe=df,
        input_columns=["i"],
        score_columns=["s"],
    )

    # Parent Table read columns straight off the dataframe.
    assert et.columns == ["i", "o", "s"]

    _log(et, mock_run)
    ev = mock_eval_logger.created_loggers[0]
    assert ev.log_example.call_count == 2
    # `o` defaults to output (not in any role list), `s` is score, `i` is input.
    ev.log_example.assert_any_call(
        inputs={"i": "i1"}, output={"o": "o1"}, scores={"s": 0.5}
    )
    ev.log_example.assert_any_call(
        inputs={"i": "i2"}, output={"o": "o2"}, scores={"s": 0.6}
    )


# MUTABLE: each run.log() builds a fresh logger; previous one is finalized.
def test_mutable_logs_fresh_each_time(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        columns=["i", "o"],
        data=[["i1", "o1"]],
        input_columns=["i"],
        log_mode="MUTABLE",
    )
    _log(et, mock_run)
    assert len(mock_eval_logger.created_loggers) == 1
    ev1 = mock_eval_logger.created_loggers[0]
    assert ev1.log_example.call_count == 1
    ev1.log_summary.assert_called_once()

    # Add a row, log again — second call builds a new logger from scratch.
    et.add_data("i2", "o2")
    et.to_json(mock_run)

    assert len(mock_eval_logger.created_loggers) == 2
    ev2 = mock_eval_logger.created_loggers[1]
    # ev2 logged BOTH rows fresh.
    assert ev2.log_example.call_count == 2
    ev2.log_summary.assert_called_once()
    # ev2 is a distinct mock from ev1.
    assert ev1 is not ev2

    # Previous logger had log_summary called before being discarded.
    assert ev1.log_summary.called


# INCREMENTAL: row index continues across batches; summary deferred (atexit).
def test_incremental_continues_row_index_and_defers_summary(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        columns=["o1", "o2"],
        data=[["x", 1], ["y", 2]],
        log_mode="INCREMENTAL",
    )
    _log(et, mock_run)

    ev = mock_eval_logger.created_loggers[0]
    assert ev.log_example.call_count == 2
    ev.log_example.assert_any_call(
        inputs={"row": 1}, output={"o1": "x", "o2": 1}, scores={}
    )
    ev.log_example.assert_any_call(
        inputs={"row": 2}, output={"o1": "y", "o2": 2}, scores={}
    )
    # Summary not called inline — deferred to atexit handler.
    ev.log_summary.assert_not_called()

    # Add another row, log again — same logger reused, row_idx continues at 3.
    et.add_data("z", 3)
    et.to_json(mock_run)

    assert len(mock_eval_logger.created_loggers) == 1  # idempotent setup
    assert ev.log_example.call_count == 3
    ev.log_example.assert_any_call(
        inputs={"row": 3}, output={"o1": "z", "o2": 3}, scores={}
    )
    ev.log_summary.assert_not_called()


# Column-role mismatch: column listed in input/output/score but not in columns.
@pytest.mark.usefixtures("mock_eval_logger")
def test_column_role_mismatch_raises(mock_run):
    et = wandb.EvalTable(
        columns=["o1", "o2"],
        data=[["x", 1]],
        input_columns=["nonexistent"],
    )
    et.bind_to_run(mock_run, "my_eval", step=0)

    with pytest.raises(ValueError, match="do not exist in the table"):
        et.to_json(mock_run)


# Nested Table inside an EvalTable cell: rejected at log time.
@pytest.mark.usefixtures("mock_eval_logger")
def test_nested_table_cell_raises(mock_run):
    inner = wandb.Table(columns=["x"], data=[["v"]])
    et = wandb.EvalTable(
        columns=["t", "n"],
        data=[[inner, 1]],
    )
    et.bind_to_run(mock_run, "my_eval", step=0)

    with pytest.raises(TypeError, match="does not support nested Tables"):
        et.to_json(mock_run)


# Logging an EvalTable to an Artifact: rejected.
@pytest.mark.usefixtures("mock_eval_logger")
def test_artifact_path_raises():
    et = wandb.EvalTable(columns=["o"], data=[["x"]])
    fake_artifact = MagicMock(spec=wandb.Artifact)

    with pytest.raises(TypeError, match="cannot be logged to a wandb.Artifact"):
        et.to_json(fake_artifact)


# Parent wandb.Table rejects EvalTable cells in its serialization path.
@pytest.mark.usefixtures("mock_eval_logger")
def test_parent_table_rejects_evaltable_cell():
    et = wandb.EvalTable(columns=["o"], data=[["x"]])
    parent = wandb.Table(columns=["c1", "c2"], data=[[et, "other"]])

    with pytest.raises(TypeError, match="cannot contain EvalTable cells"):
        parent._to_table_json()


# INCREMENTAL: atexit handler fires the deferred summary at process exit.
def test_incremental_atexit_fires_summary(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        columns=["o"],
        data=[["x"]],
        log_mode="INCREMENTAL",
    )
    et.set_summary({"final": 1.0}, auto_summarize=False)
    _log(et, mock_run)

    ev = mock_eval_logger.created_loggers[0]
    ev.log_summary.assert_not_called()  # deferred

    assert len(mock_eval_logger.atexit_handlers) == 1
    mock_eval_logger.atexit_handlers[0]()

    ev.log_summary.assert_called_once_with({"final": 1.0}, auto_summarize=False)

    # Once EvalTable has run its own summary path, the handler is a no-op.
    ev.log_summary.reset_mock()
    mock_eval_logger.atexit_handlers[0]()
    ev.log_summary.assert_not_called()


@pytest.mark.parametrize("log_mode", ["IMMUTABLE", "MUTABLE"])
def test_finish_only_supported_for_incremental(mock_eval_logger, mock_run, log_mode):
    et = wandb.EvalTable(columns=["o"], data=[["x"]], log_mode=log_mode)
    _log(et, mock_run)

    with pytest.raises(UsageError, match="only supported for log_mode='INCREMENTAL'"):
        et.finish()


def test_incremental_finish_requires_prior_log(mock_eval_logger):
    et = wandb.EvalTable(columns=["o"], data=[["x"]], log_mode="INCREMENTAL")

    with pytest.raises(UsageError, match="logged with run.log\\(\\) first"):
        et.finish()

    assert mock_eval_logger.created_loggers == []


def test_incremental_finish_with_pending_rows_warns(
    mock_eval_logger, mock_run, monkeypatch
):
    termwarn = MagicMock()
    monkeypatch.setattr(wandb, "termwarn", termwarn)

    et = wandb.EvalTable(
        columns=["o"],
        data=[["x"]],
        log_mode="INCREMENTAL",
    )
    _log(et, mock_run)
    ev = mock_eval_logger.created_loggers[0]

    et.add_data("y")

    et.finish()

    termwarn.assert_called_once_with(
        "EvalTable.finish() called with 1 row(s) added after the last run.log(); "
        "those rows will not be included in the finalized evaluation.",
        repeat=False,
    )
    ev.log_summary.assert_called_once_with(None, auto_summarize=True)


def test_incremental_finish_logs_summary_and_is_idempotent(mock_eval_logger, mock_run):
    et = wandb.EvalTable(
        columns=["o"],
        data=[["x"]],
        log_mode="INCREMENTAL",
    )
    et.set_summary({"final": 1.0}, auto_summarize=False)
    _log(et, mock_run)
    ev = mock_eval_logger.created_loggers[0]

    et.finish()
    et.finish()

    ev.log_summary.assert_called_once_with({"final": 1.0}, auto_summarize=False)

    with pytest.raises(UsageError, match="after finish\\(\\) has been called"):
        et.to_json(mock_run)


def test_incremental_atexit_warns_on_unlogged_rows(
    mock_eval_logger, mock_run, monkeypatch
):
    termwarn = MagicMock()
    monkeypatch.setattr(wandb, "termwarn", termwarn)

    et = wandb.EvalTable(
        columns=["o"],
        data=[["x"]],
        log_mode="INCREMENTAL",
    )
    _log(et, mock_run)
    ev = mock_eval_logger.created_loggers[0]
    et.add_data("y")

    mock_eval_logger.atexit_handlers[0]()

    ev.log_summary.assert_called_once_with(None, auto_summarize=True)
    termwarn.assert_called_once_with(
        "EvalTable process-exit cleanup found 1 row(s) added after the last "
        "run.log(); those rows will not be included in the finalized evaluation.",
        repeat=False,
    )


# wandb.Image cell values are unwrapped to PIL.Image before being
# passed to log_example, so weave can use its image type handler.
def test_wandb_image_cell_unwrapped_to_pil(mock_eval_logger, mock_run):
    from PIL import Image as PILImage

    pil_in = PILImage.new("RGB", (2, 2), color="red")
    wb_img = wandb.Image(pil_in)

    et = wandb.EvalTable(
        columns=["img"],
        data=[[wb_img]],
    )
    _log(et, mock_run)

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
