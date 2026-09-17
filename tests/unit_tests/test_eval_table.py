"""Unit tests for wandb.EvalTable."""

from __future__ import annotations

import datetime
import sys
import types
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest
import wandb
import wandb.data_types as wandb_data_types
from wandb.errors import UsageError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.data_types import _eval_table_writer_ces as ces_writer
from wandb.sdk.data_types import eval_table as eval_table_module
from wandb.sdk.data_types._dtypes import AnyType
from wandb.sdk.data_types.utils import history_dict_to_json


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


@pytest.fixture(autouse=True)
def default_eval_table_server_feature_disabled(monkeypatch):
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_factory.ServiceApi.feature_enabled",
        lambda self, feature: False,
    )


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
        lambda self, bound: ces_writer._CESScopeContext(
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


@pytest.mark.parametrize(
    ("server_feature_enabled", "expected_marker_type"),
    [(False, "eval-table"), (True, "eval-table-ces")],
)
def test_eval_table_defaults_backend_from_server_feature(
    server_feature_enabled,
    expected_marker_type,
    monkeypatch,
    mock_eval_logger,
    mock_ces_client,
    run,
):
    feature_enabled = MagicMock(return_value=server_feature_enabled)
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_factory.ServiceApi.feature_enabled",
        feature_enabled,
    )
    table = wandb.EvalTable(columns=["value"], data=[[1]])

    run.log({"eval": table})

    assert table.to_json(run)["_type"] == expected_marker_type
    feature_enabled.assert_called_once_with(pb.ServerFeature.EVAL_TABLES_CES)
    if server_feature_enabled:
        mock_ces_client.eval_tables.create.assert_called_once()
        mock_eval_logger._create_with_meta.assert_not_called()
    else:
        mock_eval_logger._create_with_meta.assert_called_once()
        mock_ces_client.eval_tables.create.assert_not_called()


@pytest.mark.parametrize(
    ("backend", "server_feature_enabled", "expected_marker_type"),
    [
        ("weave", True, "eval-table"),
        ("ces", False, "eval-table-ces"),
    ],
)
def test_eval_table_backend_overrides_server_default(
    backend,
    server_feature_enabled,
    expected_marker_type,
    monkeypatch,
    mock_eval_logger,
    mock_ces_client,
    run,
):
    feature_enabled = MagicMock(return_value=server_feature_enabled)
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_factory.ServiceApi.feature_enabled",
        feature_enabled,
    )
    table = wandb.EvalTable(columns=["value"], data=[[1]], backend=backend)

    run.log({"eval": table})

    assert table.to_json(run)["_type"] == expected_marker_type
    feature_enabled.assert_not_called()


def test_eval_table_default_ces_does_not_require_weave(
    monkeypatch,
    mock_ces_client,
    run,
):
    monkeypatch.setitem(sys.modules, "weave", None)
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_factory.ServiceApi.feature_enabled",
        lambda self, feature: True,
    )
    table = wandb.EvalTable(columns=["value"], data=[[1]])

    run.log({"eval": table})

    assert table.to_json(run)["_type"] == "eval-table-ces"
    mock_ces_client.eval_tables.create.assert_called_once()


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
        "backend": "ces",
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
    ("columns", "score_columns", "message"),
    [
        (["x" * 513], None, "Dataset field names"),
        (["x" * 257], ["x" * 257], "Scorer names"),
    ],
)
def test_ces_eval_table_rejects_invalid_column_name_lengths_before_network(
    mock_ces_client,
    run,
    columns,
    score_columns,
    message,
):
    et = wandb.EvalTable(
        columns=columns,
        data=[[1]],
        score_columns=score_columns,
        backend="ces",
    )

    with pytest.raises(UsageError, match=message):
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
):
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
        data=[[1]],
        backend="ces",
    )
    et.bind_to_run(run, "eval", 0)

    with pytest.raises(RuntimeError, match="temporary failure"):
        et.to_json(run)
    et.to_json(run)

    methods = (
        mock_ces_client.eval_tables.create,
        mock_ces_client.eval_tables.create_columns,
        mock_ces_client.eval_tables.add_rows,
        mock_ces_client.eval_tables.create_version,
    )
    for method in methods:
        calls = method.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["idempotency_key"] == calls[1].kwargs["idempotency_key"]


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


@pytest.mark.parametrize("backend", ["weave", "ces"])
@pytest.mark.parametrize("container", ["dict", "list"])
def test_eval_table_must_be_a_direct_history_value(
    backend,
    container,
    mock_eval_logger,
    mock_ces_client,
    run,
):
    table = wandb.EvalTable(columns=["value"], data=[[1]], backend=backend)
    nested = {"eval": table} if container == "dict" else [table]

    with pytest.raises(UsageError, match="must be logged directly"):
        run.log({"nested": nested})

    mock_eval_logger._create_with_meta.assert_not_called()
    mock_ces_client.eval_tables.create.assert_not_called()


def test_nested_scalar_history_values_remain_supported(run):
    payload = {
        "nested": {"integer": 1, "string": "value", "list": [2, 3]},
        "_step": 7,
    }

    assert history_dict_to_json(run, payload) == {
        "nested": {"integer": 1, "string": "value", "list": [2, 3]},
        "_step": 7,
    }


def test_scalar_sequence_history_does_not_get_fully_pre_walked(run):
    class FirstScalarThenFail(list):
        def __iter__(self):
            yield 1
            raise AssertionError("history conversion walked the whole sequence")

    values = FirstScalarThenFail([1, 2])
    payload = {"values": values, "_step": 7}

    assert history_dict_to_json(run, payload)["values"] is values


def test_ces_eval_table_rejects_mixed_type_mode():
    with pytest.raises(UsageError, match="allow_mixed_types=False"):
        wandb.EvalTable(
            columns=["value"],
            data=[[1]],
            allow_mixed_types=True,
            backend="ces",
        )


def test_eval_table_offline_run_fails_fast(monkeypatch, mock_eval_logger, mock_run):
    run = mock_run(settings={"entity": "e", "project": "p", "mode": "offline"})
    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    init_weave_for_run = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_weave.weave_integration.init_weave",
        init_weave_for_run,
    )

    with pytest.raises(UsageError, match="offline mode"):
        run.log({"my_eval": et})

    init_weave_for_run.assert_not_called()
    mock_eval_logger._create_with_meta.assert_not_called()


def test_eval_table_rewrites_weave_import_error(monkeypatch, run):
    monkeypatch.setitem(sys.modules, "weave", None)
    table = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    with pytest.raises(ImportError) as exc_info:
        run.log({"eval": table})

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
        "wandb.sdk.data_types._eval_table_writer_weave.weave_integration.init_weave",
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
        "wandb.sdk.data_types._eval_table_writer_weave.weave_integration.init_weave",
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
        "wandb.sdk.data_types._eval_table_writer_weave.weave_integration.init_weave",
        init_weave,
    )
    run1 = mock_run(settings={"entity": "e", "project": "p1", "mode": "online"})
    run2 = mock_run(settings={"entity": "e", "project": "p2", "mode": "online"})

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    et.bind_to_run(run1, "eval", 0)

    with pytest.raises(UsageError, match="already initialized"):
        et.bind_to_run(run2, "eval", 0)


def test_eval_table_version_mismatch_error_includes_actual_version(monkeypatch, run):
    monkeypatch.delitem(sys.modules, "weave", raising=False)
    _install_fake_weave(monkeypatch, __version__="0.1.0")
    table = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])

    with pytest.raises(ImportError) as exc_info:
        run.log({"eval": table})

    message = str(exc_info.value)
    assert message.startswith("EvalTable dependency error")
    assert "found weave==0.1.0" in message


# Standard case: 6 columns, 2 each of input/output/score; second log no-op.
def test_standard_immutable_log(mock_eval_logger, mock_wandb_log, run, monkeypatch):
    init_weave = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types._eval_table_writer_weave.weave_integration.init_weave",
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
    assert et._immutable_write_result is not None
    assert et._immutable_write_result.logged_id == "eval-1"

    # Second log on IMMUTABLE table is a no-op.
    run.log({"my_eval": et})
    assert mock_eval_logger._create_with_meta.call_count == 1
    assert init_weave.call_count == 1
    assert ev.log_example.call_count == 2
    assert ev.log_summary.call_count == 1
    mock_wandb_log.assert_warned(
        "EvalTable with log_mode='IMMUTABLE' has already been logged"
    )


def test_eval_table_records_telemetry(mock_eval_logger, run):
    """Logging an EvalTable marks the run-level eval_table telemetry feature."""
    assert not run._telemetry_obj.feature.eval_table

    et = wandb.EvalTable(columns=["input", "output"], data=[["x", "y"]])
    run.log({"eval": et})

    assert run._telemetry_obj.feature.eval_table is True


def test_telemetry_failure_does_not_repeat_immutable_write(
    monkeypatch, mock_eval_logger, run
):
    telemetry_context = MagicMock()
    telemetry_context.__enter__.return_value = MagicMock()
    telemetry_context.__exit__.side_effect = RuntimeError("telemetry failed")
    monkeypatch.setattr(
        eval_table_module.telemetry,
        "context",
        MagicMock(return_value=telemetry_context),
    )
    et = wandb.EvalTable(columns=["output"], data=[["value"]])
    et.bind_to_run(run, "eval", 0)

    with pytest.raises(RuntimeError, match="telemetry failed"):
        et.to_json(run)

    assert et.has_been_logged()
    assert et.to_json(run)["evaluate_call_id"] == "eval-1"
    mock_eval_logger._create_with_meta.assert_called_once()


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
        "wandb.sdk.data_types._eval_table_writer_weave.weave_integration.init_weave",
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


def test_to_json_requires_bind_for_default_backend(run):
    table = wandb.EvalTable(columns=["out"], data=[["x"]])

    with pytest.raises(UsageError, match="must be logged with run.log"):
        table.to_json(run)


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


def test_eval_table_rejects_unknown_backend():
    with pytest.raises(UsageError, match="Unsupported EvalTable backend"):
        wandb.EvalTable(columns=["x"], backend="unknown")


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
            backend="weave",
            unsupported_media_mode="raise",
        )
    assert "unsupported wandb media type 'Html'" in str(exc_info.value)
    assert "unsupported_media_mode='stub'" in str(exc_info.value)


@pytest.mark.usefixtures("mock_eval_logger")
def test_add_data_unsupported_wandb_value_cell_raises_in_raise_mode():
    histogram = wandb.Histogram([1, 2, 3])
    et = wandb.EvalTable(
        columns=["histogram"],
        backend="weave",
        unsupported_media_mode="raise",
    )

    with pytest.raises(TypeError) as exc_info:
        et.add_data(histogram)
    assert "unsupported wandb value type 'Histogram'" in str(exc_info.value)
    assert "unsupported_media_mode='stub'" in str(exc_info.value)

    assert et.data == []


@pytest.mark.parametrize("backend", [None, "weave", "ces"])
@pytest.mark.usefixtures("mock_eval_logger")
def test_unsupported_media_mode_rejects_unknown_mode(backend):
    with pytest.raises(ValueError, match="unsupported_media_mode"):
        wandb.EvalTable(
            columns=["x"],
            backend=backend,
            unsupported_media_mode="ignore",
        )


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


def test_weave_media_error_uses_original_integer_column(mock_eval_logger, run):
    image = wandb.Image("https://example.com/image.png")
    et = wandb.EvalTable(
        columns=[1],
        data=[[image]],
        unsupported_media_mode="raise",
    )

    with pytest.raises(TypeError, match="column 1") as exc_info:
        run.log({"my_eval": et})

    assert "column '1'" not in str(exc_info.value)


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
