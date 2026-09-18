"""Unit tests for the CES-backed wandb.EvalTable."""

from __future__ import annotations

import sys
import types
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
import wandb
from wandb.errors import UsageError
from wandb.sdk.data_types import _eval_table_writer_ces as ces_writer
from wandb.sdk.data_types._dtypes import AnyType


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
        "wandb.sdk.data_types._eval_table_writer_weave.weave_integration.init_weave",
        lambda entity, project: None,
    )
    return mock_evaluation_logger_cls


@pytest.fixture
def run(mock_run):
    return mock_run(settings={"entity": "e", "project": "p", "mode": "online"})


@pytest.fixture
def mock_ces_client(monkeypatch):
    client = MagicMock()
    client.eval_tables.create.return_value = SimpleNamespace(
        dataset_id="dataset-1",
        evaluation_id="evaluation-1",
    )
    client.eval_tables.create_version.return_value = SimpleNamespace(
        dataset_version_id="dataset-version-1",
        evaluation_version_id="evaluation-version-1",
    )
    monkeypatch.setenv(
        "CES_BASE_URL",
        "https://evaluations.example.test",
    )
    client_module = types.ModuleType("coreweave_evaluations")
    client_module.CoreWeaveEvaluations = MagicMock
    monkeypatch.setitem(sys.modules, "coreweave_evaluations", client_module)
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_ces."
        "CESEvalTableWriter._resolve_scope_context",
        lambda self, bound_run: ces_writer._CESScopeContext(
            scope_ref="scope-ref",
            api_key=None,
            access_token="token",
        ),
    )
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_ces.CESEvalTableWriter._create_client",
        lambda self, client_type, base_url, scope: client,
    )
    return client


def test_ces_eval_table_writes_columns_rows_and_version(
    mock_ces_client,
    run,
    monkeypatch,
):
    debug = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_ces._logger.debug",
        debug,
    )
    et = wandb.EvalTable(
        columns=["prompt", "truth", "answer", "confidence", "correct"],
        data=[
            ["2+2", "4", "4", 1, True],
            ["2+3", "5", "4", 0.25, False],
        ],
        input_columns=["prompt", "truth"],
        output_columns=["answer", "confidence"],
        score_columns=["correct"],
        backend="ces",
    )

    run.log({"math_eval": et})

    api = mock_ces_client.eval_tables
    assert [call[0] for call in api.method_calls] == [
        "create",
        "create_columns",
        "add_rows",
        "create_version",
    ]
    api.create.assert_called_once_with(
        "scope-ref",
        namespace="wandb",
        name="math_eval",
        idempotency_key=ANY,
    )
    api.create_columns.assert_called_once_with(
        "evaluation-1",
        namespace="wandb",
        scope_ref="scope-ref",
        dataset_fields=[
            {"source": "input", "name": "prompt", "value_type": "string"},
            {"source": "input", "name": "truth", "value_type": "string"},
            {"source": "output", "name": "answer", "value_type": "string"},
            {"source": "output", "name": "confidence", "value_type": "number"},
        ],
        scorers=[
            {"name": "correct", "value_type": "boolean"},
        ],
        idempotency_key=ANY,
    )
    api.add_rows.assert_called_once_with(
        "evaluation-1",
        namespace="wandb",
        scope_ref="scope-ref",
        rows=[
            {
                "input": {"prompt": "2+2", "truth": "4"},
                "output": {"answer": "4", "confidence": 1},
                "scores": {"correct": True},
            },
            {
                "input": {"prompt": "2+3", "truth": "5"},
                "output": {"answer": "4", "confidence": 0.25},
                "scores": {"correct": False},
            },
        ],
        idempotency_key=ANY,
    )
    api.create_version.assert_called_once_with(
        "evaluation-1",
        namespace="wandb",
        scope_ref="scope-ref",
        idempotency_key=ANY,
    )
    mock_ces_client.close.assert_called_once_with()
    debug.assert_called_once_with(
        "CES EvalTable recorded namespace=%s scope_ref=%s evaluation_version_id=%s",
        "wandb",
        "scope-ref",
        "evaluation-version-1",
    )

    marker = et.to_json(run)
    assert marker == {
        "_type": "eval-table-ces",
        "schema_version": 1,
        "ncols": 5,
        "nrows": 2,
        "log_mode": "IMMUTABLE",
        "evaluation_id": "evaluation-1",
        "evaluation_version_id": "evaluation-version-1",
        "dataset_id": "dataset-1",
        "dataset_version_id": "dataset-version-1",
    }
    assert "evaluate_call_id" not in marker
    assert et._immutable_write_result is not None
    assert et._immutable_write_result.logged_id == "evaluation-version-1"


def test_ces_eval_table_stubs_media_until_native_support_exists(
    mock_ces_client,
    mock_wandb_log,
    run,
):
    from PIL import Image as PILImage

    image = wandb.Image(PILImage.new("RGB", (2, 2), color="red"))
    et = wandb.EvalTable(
        columns=["image"],
        data=[[image]],
        backend="ces",
    )

    run.log({"media_eval": et})

    rows = mock_ces_client.eval_tables.add_rows.call_args.kwargs["rows"]
    assert rows == [
        {
            "input": {"row": 1},
            "output": {"image": "[wandb.Image not yet supported]"},
            "scores": {},
        }
    ]
    mock_wandb_log.assert_warned(
        "wandb.Image values are not yet supported by CES EvalTable logging"
    )


def test_ces_eval_table_raises_for_media_in_raise_mode(mock_ces_client):
    from PIL import Image as PILImage

    image = wandb.Image(PILImage.new("RGB", (2, 2), color="red"))

    with pytest.raises(TypeError, match="unsupported wandb media type 'Image'"):
        wandb.EvalTable(
            columns=["image"],
            data=[[image]],
            backend="ces",
            unsupported_media_mode="raise",
        )

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_batches_rows_by_encoded_bytes(
    mock_ces_client,
    run,
    monkeypatch,
):
    row = {
        "input": {"prompt": "é" * 40},
        "output": {"answer": "yes"},
        "scores": {},
    }
    single_row_body_size = len(ces_writer._encode_json({"rows": [row]}))
    monkeypatch.setattr(
        ces_writer,
        "_TARGET_ROW_BATCH_BODY_BYTES",
        single_row_body_size - 1,
    )
    et = wandb.EvalTable(
        columns=["prompt", "answer"],
        data=[["é" * 40, "yes"], ["é" * 40, "yes"]],
        input_columns=["prompt"],
        output_columns=["answer"],
        backend="ces",
    )

    run.log({"eval": et})

    calls = mock_ces_client.eval_tables.add_rows.call_args_list
    assert [call.kwargs["rows"] for call in calls] == [[row], [row]]
    keys = [call.kwargs["idempotency_key"] for call in calls]
    assert len(set(keys)) == 2
    assert keys[0].endswith("-rows-0")
    assert keys[1].endswith("-rows-1")


@pytest.mark.parametrize(
    ("separator_bytes", "expected_batch_sizes"),
    [(1, [2, 1]), (0, [1, 1, 1])],
)
def test_ces_eval_table_batch_size_counts_row_separators(
    separator_bytes,
    expected_batch_sizes,
):
    row = {"input": {"value": "same"}, "output": None, "scores": {}}
    row_size = len(ces_writer._encode_json(row))
    target_size = ces_writer._ROW_BATCH_ENVELOPE_BYTES + 2 * row_size + separator_bytes
    batches = list(
        ces_writer._iter_row_batches(
            [row, row, row],
            max_body_bytes=16 << 20,
            target_body_bytes=target_size,
            max_rows=10_000,
        )
    )

    assert [len(batch) for batch in batches] == expected_batch_sizes


def test_ces_eval_table_batches_rows_by_count(
    mock_ces_client,
    run,
    monkeypatch,
):
    monkeypatch.setattr(ces_writer, "_MAX_ROWS_PER_BATCH", 2)
    et = wandb.EvalTable(
        columns=["value"],
        data=[[index] for index in range(5)],
        output_columns=["value"],
        backend="ces",
    )

    run.log({"eval": et})

    calls = mock_ces_client.eval_tables.add_rows.call_args_list
    assert [len(call.kwargs["rows"]) for call in calls] == [2, 2, 1]
    assert [call[0] for call in mock_ces_client.eval_tables.method_calls] == [
        "create",
        "create_columns",
        "add_rows",
        "add_rows",
        "add_rows",
        "create_version",
    ]


def test_ces_eval_table_rejects_oversized_row_before_network(
    mock_ces_client,
    run,
    monkeypatch,
):
    value = "large" * 100
    row = {
        "input": {"row": 0},
        "output": {"value": value},
        "scores": {},
    }
    body_size = len(ces_writer._encode_json({"rows": [row]}))
    monkeypatch.setattr(ces_writer, "_MAX_REQUEST_BODY_BYTES", body_size)
    et = wandb.EvalTable(
        columns=["value"],
        data=[[value]],
        output_columns=["value"],
        backend="ces",
    )

    with pytest.raises(UsageError, match="row at index 0"):
        run.log({"eval": et})

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_rejects_total_row_count_before_network(
    mock_ces_client,
    run,
    monkeypatch,
):
    monkeypatch.setattr(ces_writer, "_MAX_ROWS_PER_TABLE", 2)
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1], [2], [3]],
        output_columns=["value"],
        backend="ces",
    )

    with pytest.raises(UsageError, match="at most 2 rows per table"):
        run.log({"eval": et})

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_does_not_cut_version_after_batch_failure(
    mock_ces_client,
    run,
    monkeypatch,
):
    monkeypatch.setattr(ces_writer, "_MAX_ROWS_PER_BATCH", 1)
    mock_ces_client.eval_tables.add_rows.side_effect = [
        None,
        RuntimeError("batch failed"),
    ]
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1], [2]],
        output_columns=["value"],
        backend="ces",
    )

    with pytest.raises(RuntimeError, match="batch failed"):
        run.log({"eval": et})

    mock_ces_client.eval_tables.create_version.assert_not_called()
    mock_ces_client.close.assert_called_once_with()


def test_ces_eval_table_infers_python_and_numpy_integers(
    mock_ces_client,
    run,
):
    np = pytest.importorskip("numpy")
    et = wandb.EvalTable(
        columns=["python_int", "numpy_int", "numeric"],
        data=[[1, np.int64(2), np.int64(3)], [4, np.int32(5), np.float64(6.5)]],
        output_columns=["python_int", "numpy_int", "numeric"],
        backend="ces",
    )

    run.log({"typed_eval": et})

    fields = mock_ces_client.eval_tables.create_columns.call_args.kwargs[
        "dataset_fields"
    ]
    assert fields == [
        {"source": "input", "name": "row", "value_type": "integer"},
        {"source": "output", "name": "python_int", "value_type": "integer"},
        {"source": "output", "name": "numpy_int", "value_type": "integer"},
        {"source": "output", "name": "numeric", "value_type": "number"},
    ]


def test_ces_eval_table_classifies_integer_valued_floats_as_numbers(
    mock_ces_client,
    run,
):
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1.0], [2.0], [3.0]],
        output_columns=["value"],
        backend="ces",
    )

    run.log({"typed_eval": et})

    assert mock_ces_client.eval_tables.create_columns.call_args.kwargs[
        "dataset_fields"
    ] == [
        {"source": "input", "name": "row", "value_type": "integer"},
        {"source": "output", "name": "value", "value_type": "number"},
    ]


def test_ces_eval_table_serializes_nan_as_typed_null(mock_ces_client, run):
    et = wandb.EvalTable(
        columns=["value"],
        data=[[float("nan")]],
        output_columns=["value"],
        backend="ces",
    )

    run.log({"nan_eval": et})

    assert mock_ces_client.eval_tables.create_columns.call_args.kwargs[
        "dataset_fields"
    ] == [
        {"source": "input", "name": "row", "value_type": "integer"},
        {"source": "output", "name": "value", "value_type": "number"},
    ]
    assert mock_ces_client.eval_tables.add_rows.call_args.kwargs["rows"][0][
        "output"
    ] == {"value": None}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([[None], [None]], "all-null"),
        ([[float("inf")]], "non-finite"),
        ([[{"nested": True}]], "only primitive values"),
    ],
)
def test_ces_eval_table_rejects_invalid_columns_before_network(
    mock_ces_client,
    run,
    data,
    message,
):
    et = wandb.EvalTable(
        columns=["value"],
        data=data,
        backend="ces",
    )
    with pytest.raises(UsageError, match=message):
        run.log({"invalid_eval": et})

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_rejects_mixed_column_types_before_network(
    mock_ces_client,
):
    with pytest.raises(TypeError, match="incompatible types"):
        wandb.EvalTable(
            columns=["value"],
            data=[["x"], [1]],
            backend="ces",
        )

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_rejects_mixed_types_with_permissive_dtype_before_network(
    mock_ces_client,
    run,
):
    et = wandb.EvalTable(
        columns=["value"],
        data=[[True], [1]],
        dtype=AnyType,
        backend="ces",
    )

    with pytest.raises(UsageError, match="mixes 'boolean' and 'integer'"):
        run.log({"mixed_eval": et})

    mock_ces_client.eval_tables.create.assert_not_called()


@pytest.mark.parametrize(
    (
        "columns",
        "input_columns",
        "output_columns",
        "score_columns",
        "message",
    ),
    [
        (["x" * 513], ["x" * 513], None, None, "input column names"),
        (["x" * 513], None, ["x" * 513], None, "output column names"),
        (["x" * 257], None, None, ["x" * 257], "score column names"),
    ],
)
def test_ces_eval_table_rejects_invalid_column_name_lengths_before_network(
    mock_ces_client,
    run,
    columns,
    input_columns,
    output_columns,
    score_columns,
    message,
):
    et = wandb.EvalTable(
        columns=columns,
        data=[[1]],
        input_columns=input_columns,
        output_columns=output_columns,
        score_columns=score_columns,
        backend="ces",
    )

    with pytest.raises(UsageError, match=message):
        run.log({"invalid_eval": et})

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_describes_field_limit_as_input_and_output_columns(
    monkeypatch,
    mock_ces_client,
    run,
):
    monkeypatch.setattr(ces_writer, "_MAX_DATASET_FIELDS", 1)
    et = wandb.EvalTable(
        columns=["prompt", "answer"],
        data=[["question", "response"]],
        input_columns=["prompt"],
        output_columns=["answer"],
        backend="ces",
    )

    with pytest.raises(
        UsageError,
        match="at most 1 input and output columns combined",
    ):
        run.log({"invalid_eval": et})

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_rejects_invalid_table_name_length_before_network(
    mock_ces_client,
    run,
):
    et = wandb.EvalTable(columns=["value"], data=[[1]], backend="ces")

    with pytest.raises(UsageError, match="EvalTable names"):
        run.log({"x" * 257: et})

    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_error_uses_original_integer_column(mock_ces_client, run):
    et = wandb.EvalTable(
        columns=[3],
        data=[[float("inf")]],
        backend="ces",
    )

    with pytest.raises(UsageError, match="column 3") as exc_info:
        run.log({"invalid_eval": et})

    assert "column '3'" not in str(exc_info.value)
    mock_ces_client.eval_tables.create.assert_not_called()


def test_ces_eval_table_requires_base_url(monkeypatch, mock_run):
    monkeypatch.delenv("CES_BASE_URL", raising=False)
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "online"})
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1]],
        backend="ces",
    )

    with pytest.raises(UsageError, match="CES_BASE_URL"):
        run.log({"eval": et})


def test_ces_eval_table_requires_client_before_scope_lookup(monkeypatch, run):
    monkeypatch.setenv("CES_BASE_URL", "https://evaluations.example.test")
    et = wandb.EvalTable(columns=["value"], data=[[1]], backend="ces")
    et.bind_to_run(run, "eval", 0)
    writer = et._writer
    assert isinstance(writer, ces_writer.CESEvalTableWriter)
    execute_graphql = MagicMock()
    writer._bound = replace(
        writer._require_bound(),
        service_api=SimpleNamespace(
            api_key="secret",
            access_token=MagicMock(),
            execute_graphql=execute_graphql,
        ),
    )
    monkeypatch.setitem(sys.modules, "coreweave_evaluations", None)

    with pytest.raises(UsageError, match="coreweave_evaluations"):
        et.to_json(run)

    execute_graphql.assert_not_called()


def test_ces_eval_table_resolves_project_scope_with_api_key(run):
    writer = ces_writer.CESEvalTableWriter()
    writer.bind_to_run(run, "eval", 0)
    service_api = SimpleNamespace(
        api_key="secret",
        access_token=MagicMock(),
        execute_graphql=MagicMock(
            return_value={"project": {"internalId": "opaque-project-id"}}
        ),
    )
    writer._bound = replace(writer._require_bound(), service_api=service_api)

    scope = writer._resolve_scope_context(writer._require_bound())

    assert scope.scope_ref == "opaque-project-id"
    assert scope.api_key == "secret"
    assert scope.access_token is None
    service_api.execute_graphql.assert_called_once_with(
        ces_writer._PROJECT_SCOPE_QUERY,
        variables={"entity": "e", "project": "p"},
    )
    service_api.access_token.assert_not_called()


def test_ces_scope_context_repr_redacts_credentials():
    scope = ces_writer._CESScopeContext(
        scope_ref="scope-ref",
        api_key="api-secret",
        access_token="token-secret",
    )

    assert repr(scope) == "_CESScopeContext(scope_ref='scope-ref')"


def test_ces_eval_table_uses_federated_access_token(run):
    writer = ces_writer.CESEvalTableWriter()
    writer.bind_to_run(run, "eval", 0)
    writer._bound = replace(
        writer._require_bound(),
        service_api=SimpleNamespace(
            api_key=None,
            access_token=MagicMock(return_value="access-token"),
            execute_graphql=MagicMock(
                return_value={"project": {"internalId": "opaque-project-id"}}
            ),
        ),
    )

    scope = writer._resolve_scope_context(writer._require_bound())

    assert scope.api_key is None
    assert scope.access_token == "access-token"


@pytest.mark.parametrize(
    ("api_key", "access_token"),
    [("run-api-key", None), (None, "run-access-token")],
)
def test_ces_client_uses_only_the_run_credentials(api_key, access_token):
    class EnvironmentDefaultingClient:
        def __init__(self, *, base_url, api_key, bearer_token):
            self.base_url = base_url
            self.api_key = api_key if api_key is not None else "environment-api-key"
            self.bearer_token = (
                bearer_token if bearer_token is not None else "environment-access-token"
            )

    writer = ces_writer.CESEvalTableWriter()
    scope = ces_writer._CESScopeContext(
        scope_ref="scope-ref",
        api_key=api_key,
        access_token=access_token,
    )

    client = writer._create_client(
        EnvironmentDefaultingClient,
        "https://evaluations.example.test",
        scope,
    )

    assert client.api_key == api_key
    assert client.bearer_token == access_token


def test_ces_eval_table_retries_with_stable_idempotency_keys(
    mock_ces_client,
    run,
    monkeypatch,
):
    monkeypatch.setattr(ces_writer, "_MAX_ROWS_PER_BATCH", 1)
    version = SimpleNamespace(
        dataset_version_id="dataset-version-1",
        evaluation_version_id="evaluation-version-1",
    )
    mock_ces_client.eval_tables.create_version.side_effect = [
        RuntimeError("temporary failure"),
        version,
    ]
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1], [2]],
        output_columns=["value"],
        backend="ces",
    )
    et.bind_to_run(run, "eval", 0)

    with pytest.raises(RuntimeError, match="temporary failure"):
        et.to_json(run)
    et.to_json(run)

    methods = (
        mock_ces_client.eval_tables.create,
        mock_ces_client.eval_tables.create_columns,
        mock_ces_client.eval_tables.create_version,
    )
    for method in methods:
        calls = method.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["idempotency_key"] == calls[1].kwargs["idempotency_key"]

    row_calls = mock_ces_client.eval_tables.add_rows.call_args_list
    assert len(row_calls) == 4
    first_attempt_keys = [call.kwargs["idempotency_key"] for call in row_calls[:2]]
    retry_keys = [call.kwargs["idempotency_key"] for call in row_calls[2:]]
    assert first_attempt_keys == retry_keys
    assert len(set(first_attempt_keys)) == 2


def test_ces_eval_table_run_location_stabilizes_idempotency_keys(
    mock_ces_client,
    run,
):
    first = wandb.EvalTable(
        columns=["value"],
        data=[[1]],
        backend="ces",
    )
    second = wandb.EvalTable(
        columns=["value"],
        data=[[2]],
        backend="ces",
    )
    first.bind_to_run(run, "eval", 7)
    second.bind_to_run(run, "eval", 7)

    first.to_json(run)
    second.to_json(run)

    methods = (
        mock_ces_client.eval_tables.create,
        mock_ces_client.eval_tables.create_columns,
        mock_ces_client.eval_tables.add_rows,
        mock_ces_client.eval_tables.create_version,
    )
    for method in methods:
        calls = method.call_args_list
        assert len(calls) == 2
        # Content is not part of request identity; CES detects body mismatches.
        assert calls[0].kwargs["idempotency_key"] == calls[1].kwargs["idempotency_key"]


def test_ces_eval_table_rejects_mixed_type_mode():
    with pytest.raises(UsageError, match="allow_mixed_types=False"):
        wandb.EvalTable(
            columns=["value"],
            data=[[1]],
            allow_mixed_types=True,
            backend="ces",
        )
