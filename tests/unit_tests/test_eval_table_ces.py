"""Unit tests for the CES-backed wandb.EvalTable."""

from __future__ import annotations

import gzip
import json
import os
from typing import Any
from unittest.mock import MagicMock

import pytest
import wandb
from google.protobuf.message import Message
from wandb.errors import CommError, UsageError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.data_types._dtypes import AnyType
from wandb.sdk.data_types.eval_table import _writer_ces as ces
from wandb.sdk.interface.interface import InterfaceBase


@pytest.fixture
def run(mock_run):
    return mock_run(settings={"entity": "e", "project": "p", "mode": "online"})


@pytest.fixture(autouse=True)
def default_eval_table_server_feature_enabled(monkeypatch):
    monkeypatch.setattr(
        "wandb.apis.public.service_api.ServiceApi.feature_enabled",
        lambda self, feature: True,
    )


def _upload_eval_table_result(
    response: pb.UploadEvalTableResponse,
) -> pb.Result:
    return pb.Result(response=pb.Response(upload_eval_table_response=response))


_UPLOADED = pb.UploadEvalTableResponse(
    evaluation_id="evaluation-1",
    evaluation_version_id="evaluation-version-1",
    dataset_id="dataset-1",
    dataset_version_id="dataset-version-1",
)


@pytest.fixture
def deliver_upload_eval_table(monkeypatch) -> MagicMock:
    """Replace wandb-core's EvalTable upload with one that succeeds."""
    deliver = MagicMock()
    deliver.return_value.wait_or.return_value = _upload_eval_table_result(_UPLOADED)
    monkeypatch.setattr(InterfaceBase, "deliver_upload_eval_table", deliver)
    return deliver


def _sent(deliver: MagicMock) -> list[pb.UploadEvalTableRequest]:
    """Return the requests sent to wandb-core."""
    return [call.args[0] for call in deliver.call_args_list]


def _value(value: pb.EvalTableValue) -> Any:
    """Decode a typed value, parsing W&B media JSON."""
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "bool_value":
        return value.bool_value
    if kind == "int_value":
        return value.int_value
    if kind == "number_value":
        return value.number_value
    if kind == "string_value":
        return value.string_value
    if kind == "json_value":
        return json.loads(value.json_value)
    return json.loads(value.wandb_media_json)


def _rows(request: pb.UploadEvalTableRequest) -> list[dict[str, Any]]:
    """Decode the request's typed rows into CES row objects."""
    names = {
        source: [
            field.name for field in request.dataset_fields if field.source == source
        ]
        for source in ("input", "output")
    }
    scorer_names = [scorer.name for scorer in request.scorers]

    rows = []
    for row in request.rows:
        decoded: dict[str, Any] = {}
        for source in ("input", "output"):
            values = row.input if source == "input" else row.output
            decoded[source] = (
                dict(zip(names[source], map(_value, values.values), strict=True))
                if row.HasField(source)
                else None
            )
        decoded["scores"] = dict(
            zip(scorer_names, map(_value, row.scores), strict=True)
        )
        if row.example_key:
            decoded["example_key"] = row.example_key
        rows.append(decoded)
    return rows


def _read_rows_file(path: str) -> list[pb.EvalTableRow]:
    """Read a gzipped file of rows, each preceded by its size as a varint."""
    with gzip.open(path) as file:
        data = file.read()

    rows = []
    position = 0
    while position < len(data):
        size = shift = 0
        while True:
            byte = data[position]
            position += 1
            size |= (byte & 0x7F) << shift
            shift += 7
            if byte < 0x80:
                break
        rows.append(pb.EvalTableRow.FromString(data[position : position + size]))
        position += size
    return rows


def _as_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert messages to dicts of their set fields."""
    return [
        {field.name: value for field, value in message.ListFields()}
        for message in messages
    ]


def test_ces_eval_table_writes_columns_rows_and_version(
    deliver_upload_eval_table,
    run,
    monkeypatch,
):
    debug = MagicMock()
    monkeypatch.setattr(
        "wandb.sdk.data_types.eval_table._writer_ces._logger.debug",
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

    [request] = _sent(deliver_upload_eval_table)
    assert request.name == "math_eval"
    assert _as_dicts(request.dataset_fields) == [
        {"source": "input", "name": "prompt", "value_type": "string"},
        {"source": "input", "name": "truth", "value_type": "string"},
        {"source": "output", "name": "answer", "value_type": "string"},
        {"source": "output", "name": "confidence", "value_type": "number"},
    ]
    assert _as_dicts(request.scorers) == [
        {"name": "correct", "value_type": "boolean"},
    ]
    assert _rows(request) == [
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
    ]
    debug.assert_called_once_with(
        "CES EvalTable recorded evaluation_version_id=%s",
        "evaluation-version-1",
    )

    history_value = et.to_json(run)
    assert history_value == {
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
    assert "evaluate_call_id" not in history_value
    assert et._immutable_write_result is not None
    assert et._immutable_write_result.logged_id == "evaluation-version-1"


def test_ces_eval_table_sends_large_tables_in_a_rows_file(
    deliver_upload_eval_table,
    run,
    monkeypatch,
):
    monkeypatch.setattr(ces, "_ROWS_FILE_THRESHOLD_BYTES", 0)
    # Long enough for a multi-byte size.
    long = "c" * 200
    et = wandb.EvalTable(
        columns=["value"],
        data=[["a\nb"], [long]],
        output_columns=["value"],
        backend="ces",
    )

    run.log({"eval": et})

    [request] = _sent(deliver_upload_eval_table)
    assert not request.rows
    request.rows.extend(_read_rows_file(request.rows_file_path))
    os.remove(request.rows_file_path)
    assert _rows(request) == [
        {
            "input": None,
            "output": {"value": "a\nb"},
            "scores": {},
            "example_key": "1",
        },
        {"input": None, "output": {"value": long}, "scores": {}, "example_key": "2"},
    ]


def test_ces_eval_table_without_inputs_keys_rows_by_position(
    deliver_upload_eval_table,
    run,
):
    et = wandb.EvalTable(
        columns=["answer", "correct"],
        data=[["4", True], ["5", False]],
        score_columns=["correct"],
        backend="ces",
    )

    run.log({"eval": et})

    [request] = _sent(deliver_upload_eval_table)
    assert _rows(request) == [
        {
            "input": None,
            "output": {"answer": "4"},
            "scores": {"correct": True},
            "example_key": "1",
        },
        {
            "input": None,
            "output": {"answer": "5"},
            "scores": {"correct": False},
            "example_key": "2",
        },
    ]


def test_ces_eval_table_stubs_media_until_native_support_exists(
    deliver_upload_eval_table,
    mock_wandb_log,
    run,
):
    histogram = wandb.Histogram([1, 2, 3])
    table = wandb.EvalTable(
        columns=["histogram"],
        data=[[histogram]],
        backend="ces",
    )

    run.log({"media_eval": table})

    [request] = _sent(deliver_upload_eval_table)
    rows = _rows(request)
    assert rows[0]["output"]["histogram"] == "[wandb.Histogram not yet supported]"
    mock_wandb_log.assert_warned("wandb.Histogram values are not yet supported")


def test_ces_eval_table_writes_supported_media(
    deliver_upload_eval_table,
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

    [request] = _sent(deliver_upload_eval_table)
    rows = _rows(request)
    image_value = rows[0]["output"]["image"]
    assert image_value["_type"] == "image-file"
    assert image_value["path"].startswith("media/eval_tables/images/")
    assert request.dataset_fields[0].wandb_media_type == "image-file"


@pytest.mark.parametrize(
    ("oversized_media_cells", "expected_metrics"),
    [
        (0, ["eval_table_ces_media_write"]),
        (
            1,
            [
                "eval_table_ces_media_write",
                "eval_table_ces_media_write_with_oversized_cells",
            ],
        ),
    ],
)
def test_ces_eval_table_media_telemetry_counts_affected_writes(
    monkeypatch,
    oversized_media_cells,
    expected_metrics,
):
    recorder = MagicMock()
    monkeypatch.setattr(ces, "get_telemetry_recorder", lambda: recorder)
    prepared = ces._CESWritePayloads(
        dataset_fields=[],
        scorers=[],
        rows=[],
        upload_media_paths=[],
        media_cells_examined=1,
        oversized_media_cells=oversized_media_cells,
        oversized_locations=(),
    )

    ces.CESWriter()._record_media_telemetry(prepared)

    assert [
        call.args[0] for call in recorder.increment_counter.call_args_list
    ] == expected_metrics
    recorder.log.assert_not_called()


def test_ces_eval_table_writes_supported_media_in_raise_mode(
    deliver_upload_eval_table, run
):
    from PIL import Image as PILImage

    image = wandb.Image(PILImage.new("RGB", (2, 2), color="red"))

    table = wandb.EvalTable(
        columns=["image"],
        data=[[image]],
        backend="ces",
        unsupported_media_mode="raise",
    )
    run.log({"media_eval": table})

    [request] = _sent(deliver_upload_eval_table)
    rows = _rows(request)
    assert rows[0]["output"]["image"]["_type"] == "image-file"


def test_ces_writer_validates_cells_during_construction():
    nested_table = wandb.Table(columns=["value"], data=[[1]])

    with pytest.raises(TypeError, match="does not support nested Tables"):
        wandb.EvalTable(
            columns=["table"],
            data=[[nested_table]],
            backend="ces",
        )


def test_ces_eval_table_rejects_total_row_count_before_network(
    deliver_upload_eval_table,
    run,
    monkeypatch,
):
    monkeypatch.setattr(ces, "_MAX_ROWS_PER_TABLE", 2)
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1], [2], [3]],
        output_columns=["value"],
        backend="ces",
    )

    with pytest.raises(UsageError, match="at most 2 rows per table"):
        run.log({"eval": et})

    deliver_upload_eval_table.assert_not_called()


def test_ces_eval_table_raises_upload_error(deliver_upload_eval_table, run):
    deliver_upload_eval_table.return_value.wait_or.return_value = (
        _upload_eval_table_result(
            pb.UploadEvalTableResponse(error_message="upload failed")
        )
    )
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1]],
        output_columns=["value"],
        backend="ces",
    )

    with pytest.raises(CommError, match="upload failed"):
        run.log({"eval": et})

    assert et._immutable_write_result is None


def test_ces_eval_table_sends_values_as_typed_cells(
    deliver_upload_eval_table,
    run,
):
    et = wandb.EvalTable(
        columns=["prompt", "passed", "count", "ratio", "note", "grade"],
        data=[["a", True, 3, 0.5, None, 1], ["b", False, 4, 1.5, "x", 2.5]],
        input_columns=["prompt"],
        output_columns=["passed", "count", "ratio", "note"],
        score_columns=["grade"],
        backend="ces",
    )

    run.log({"typed_eval": et})

    [request] = _sent(deliver_upload_eval_table)
    assert [
        (
            [value.WhichOneof("value") for value in row.input.values],
            [value.WhichOneof("value") for value in row.output.values],
            [value.WhichOneof("value") for value in row.scores],
        )
        for row in request.rows
    ] == [
        (
            ["string_value"],
            ["bool_value", "int_value", "number_value", None],
            ["int_value"],
        ),
        (
            ["string_value"],
            ["bool_value", "int_value", "number_value", "string_value"],
            ["number_value"],
        ),
    ]
    assert _rows(request) == [
        {
            "input": {"prompt": "a"},
            "output": {"passed": True, "count": 3, "ratio": 0.5, "note": None},
            "scores": {"grade": 1},
        },
        {
            "input": {"prompt": "b"},
            "output": {"passed": False, "count": 4, "ratio": 1.5, "note": "x"},
            "scores": {"grade": 2.5},
        },
    ]


def test_ces_eval_table_rejects_integers_outside_int64(
    deliver_upload_eval_table,
    run,
):
    et = wandb.EvalTable(
        columns=["count"],
        data=[[2**63]],
        output_columns=["count"],
        backend="ces",
    )

    with pytest.raises(UsageError, match="outside the 64-bit range"):
        run.log({"eval": et})

    deliver_upload_eval_table.assert_not_called()


def test_ces_eval_table_infers_python_and_numpy_integers(
    deliver_upload_eval_table,
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

    [request] = _sent(deliver_upload_eval_table)
    assert _as_dicts(request.dataset_fields) == [
        {"source": "output", "name": "python_int", "value_type": "integer"},
        {"source": "output", "name": "numpy_int", "value_type": "integer"},
        {"source": "output", "name": "numeric", "value_type": "number"},
    ]


def test_ces_eval_table_classifies_integer_valued_floats_as_numbers(
    deliver_upload_eval_table,
    run,
):
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1.0], [2.0], [3.0]],
        output_columns=["value"],
        backend="ces",
    )

    run.log({"typed_eval": et})

    [request] = _sent(deliver_upload_eval_table)
    assert _as_dicts(request.dataset_fields) == [
        {"source": "output", "name": "value", "value_type": "number"},
    ]


def test_ces_eval_table_serializes_nan_as_typed_null(deliver_upload_eval_table, run):
    et = wandb.EvalTable(
        columns=["value"],
        data=[[float("nan")]],
        output_columns=["value"],
        backend="ces",
    )

    run.log({"nan_eval": et})

    [request] = _sent(deliver_upload_eval_table)
    assert _as_dicts(request.dataset_fields) == [
        {"source": "output", "name": "value", "value_type": "number"},
    ]
    assert _rows(request)[0]["output"] == {"value": None}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([[None], [None]], "all-null"),
        ([[float("inf")]], "non-finite"),
        ([[{"nested": True}]], "only primitive values"),
    ],
)
def test_ces_eval_table_rejects_invalid_columns_before_network(
    deliver_upload_eval_table,
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

    deliver_upload_eval_table.assert_not_called()


def test_ces_eval_table_rejects_mixed_column_types_on_construction():
    with pytest.raises(TypeError, match="incompatible types"):
        wandb.EvalTable(
            columns=["value"],
            data=[["x"], [1]],
            backend="ces",
        )


def test_ces_eval_table_rejects_mixed_types_with_permissive_dtype_before_network(
    deliver_upload_eval_table,
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

    deliver_upload_eval_table.assert_not_called()


def test_ces_eval_table_reports_media_types_in_mixed_column_error():
    writer = ces.CESWriter()

    with pytest.raises(UsageError, match="mixes 'image-file' and 'audio-file'"):
        writer._merge_field_type(
            "media",
            ces._CESFieldType("json", "image-file"),
            ces._CESFieldType("json", "audio-file"),
        )


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
    deliver_upload_eval_table,
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

    deliver_upload_eval_table.assert_not_called()


def test_ces_eval_table_describes_field_limit_as_input_and_output_columns(
    monkeypatch,
    deliver_upload_eval_table,
    run,
):
    monkeypatch.setattr(ces, "_MAX_DATASET_FIELDS", 1)
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

    deliver_upload_eval_table.assert_not_called()


def test_ces_eval_table_rejects_invalid_table_name_length_before_network(
    deliver_upload_eval_table,
    run,
):
    et = wandb.EvalTable(columns=["value"], data=[[1]], backend="ces")

    with pytest.raises(UsageError, match="EvalTable names"):
        run.log({"x" * 257: et})

    deliver_upload_eval_table.assert_not_called()


def test_ces_error_uses_original_integer_column(deliver_upload_eval_table, run):
    et = wandb.EvalTable(
        columns=[3],
        data=[[float("inf")]],
        backend="ces",
    )

    with pytest.raises(UsageError, match="column 3") as exc_info:
        run.log({"invalid_eval": et})

    assert "column '3'" not in str(exc_info.value)
    deliver_upload_eval_table.assert_not_called()


def test_ces_eval_table_retry_resends_request(deliver_upload_eval_table, run):
    deliver_upload_eval_table.return_value.wait_or.side_effect = [
        _upload_eval_table_result(pb.UploadEvalTableResponse(error_message="failed")),
        _upload_eval_table_result(_UPLOADED),
    ]
    et = wandb.EvalTable(
        columns=["value"],
        data=[[1], [2]],
        output_columns=["value"],
        backend="ces",
    )
    et.bind_to_run(run, "eval", 7)

    with pytest.raises(CommError, match="failed"):
        et.to_json(run)
    et.to_json(run)

    first, retry = _sent(deliver_upload_eval_table)
    assert first == retry


def test_ces_eval_table_rejects_mixed_type_mode():
    with pytest.raises(UsageError, match="allow_mixed_types=False"):
        wandb.EvalTable(
            columns=["value"],
            data=[[1]],
            allow_mixed_types=True,
            backend="ces",
        )
