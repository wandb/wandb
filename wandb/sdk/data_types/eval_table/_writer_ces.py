from __future__ import annotations

import gzip
import logging
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from typing_extensions import NotRequired, TypedDict

import wandb
from wandb.analytics import get_telemetry_recorder
from wandb.analytics.opentelemetry.opentelemetry_proxy import LowCardinalityAttributes
from wandb.errors import CommError, UsageError
from wandb.proto import wandb_internal_pb2 as pb
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.base_types.wb_value import WBValue
from wandb.sdk.data_types.eval_table import _media_ces
from wandb.sdk.data_types.eval_table._media_ces import _encode_json
from wandb.sdk.data_types.eval_table._writer import WriteResult, WriteRow
from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


_logger = logging.getLogger(__name__)

# Tables with more serialized row bytes than this send their rows to
# wandb-core in a file, keeping requests far below the 2 GiB message limit.
_ROWS_FILE_THRESHOLD_BYTES = 64 << 20
# Evaluations request-schema limits.
_MAX_DATASET_FIELDS = 10_000
_MAX_DATASET_FIELD_NAME_LENGTH = 512
_MAX_EVAL_TABLE_NAME_LENGTH = 256
# Allow ten count-limited batches while failing fast on runaway tables.
_MAX_ROWS_PER_TABLE = 10_000
_MAX_SCORERS = 256
_MAX_SCORER_NAME_LENGTH = 256
_MAX_OVERSIZED_MEDIA_LOCATIONS = 5
# EvalTableValue.int_value is an int64.
_MIN_INT64 = -(2**63)
_MAX_INT64 = 2**63 - 1

PrimitiveValueType = Literal["boolean", "integer", "number", "string"]
_CESFieldSource = Literal["input", "output"]


class _CESRow(TypedDict):
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    scores: dict[str, Any]
    example_key: NotRequired[str]


@dataclass(frozen=True)
class _CESFieldType:
    """Track a column's value schema and build its CES field declaration."""

    value_type: PrimitiveValueType | Literal["json"]
    media_type: _media_ces.MediaType | None = None

    def declaration(self, source: _CESFieldSource, name: str) -> pb.EvalTableField:
        """Build the CES field declaration for this observed column type."""
        result = pb.EvalTableField(
            source=source,
            name=name,
            value_type=self.value_type,
        )
        if self.media_type is not None:
            result.wandb_media_type = self.media_type
        return result


@dataclass(frozen=True)
class _BoundRun:
    run: LocalRun
    eval_table_key: str


@dataclass(frozen=True)
class _CESWritePayloads:
    dataset_fields: list[pb.EvalTableField]
    scorers: list[pb.EvalTableScorer]
    rows: list[pb.EvalTableRow]
    upload_media_paths: list[str]
    media_cells_examined: int
    oversized_media_cells: int
    oversized_locations: tuple[str, ...]


def _ces_row(
    *,
    row_index: int,
    inputs: dict[str, Any],
    output: dict[str, Any] | None,
    scores: dict[str, Any],
) -> _CESRow:
    """Build a row-add row, keying a row without inputs by position.

    CES derives the example key of a row with inputs from a hash of its whole
    input, so comparisons match rows with equal inputs.
    """
    if inputs:
        return {"input": inputs, "output": output, "scores": scores}
    return {
        "input": None,
        "output": output,
        "scores": scores,
        "example_key": str(row_index + 1),
    }


def _encode_rows(
    rows: Sequence[_CESRow],
    *,
    dataset_fields: Sequence[pb.EvalTableField],
    scorers: Sequence[pb.EvalTableScorer],
) -> list[pb.EvalTableRow]:
    """Encode normalized rows with their values in their columns' order."""
    input_names = [field.name for field in dataset_fields if field.source == "input"]
    output_names = [field.name for field in dataset_fields if field.source == "output"]
    scorer_names = [scorer.name for scorer in scorers]

    encoded: list[pb.EvalTableRow] = []
    for row in rows:
        encoded_row = pb.EvalTableRow(
            scores=_encode_values(row["scores"], scorer_names),
            example_key=row.get("example_key", ""),
        )
        if (inputs := row["input"]) is not None:
            encoded_row.input.CopyFrom(
                pb.EvalTableRowValues(values=_encode_values(inputs, input_names))
            )
        if (output := row["output"]) is not None:
            encoded_row.output.CopyFrom(
                pb.EvalTableRowValues(values=_encode_values(output, output_names))
            )
        encoded.append(encoded_row)

    return encoded


def _encode_values(
    values: Mapping[str, Any],
    names: Sequence[str],
) -> list[pb.EvalTableValue]:
    """Encode a row's values for the named columns, null where missing."""
    return [_encode_value(values.get(name)) for name in names]


def _encode_value(value: Any) -> pb.EvalTableValue:
    """Encode a normalized cell value."""
    if value is None:
        return pb.EvalTableValue()
    if isinstance(value, bool):
        return pb.EvalTableValue(bool_value=value)
    if isinstance(value, int):
        return pb.EvalTableValue(int_value=value)
    if isinstance(value, float):
        return pb.EvalTableValue(number_value=value)
    if isinstance(value, str):
        return pb.EvalTableValue(string_value=value)
    # Normalization leaves only primitives and media, as W&B media JSON.
    return pb.EvalTableValue(wandb_media_json=_encode_json(value).decode())


def _write_rows_file(rows: Sequence[pb.EvalTableRow]) -> str:
    """Write rows to a gzipped temporary file, each preceded by its size.

    Sizes are varints, as in protobuf's length-delimited encoding.

    wandb-core deletes the file after reading it.

    Returns:
        The file's path.
    """
    file = tempfile.NamedTemporaryFile(
        prefix="wandb-eval-table-",
        suffix=".rows.pb.gz",
        delete=False,
    )
    try:
        with file, gzip.open(file, mode="wb", compresslevel=1) as rows_file:
            for row in rows:
                message = row.SerializeToString()
                rows_file.write(_encode_varint(len(message)))
                rows_file.write(message)
    except BaseException:
        # Delete the partial file, then propagate the original error.
        os.remove(file.name)
        raise

    return file.name


def _encode_varint(value: int) -> bytes:
    """Encode a non-negative integer as a protobuf varint."""
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _upload_eval_table(
    run: LocalRun,
    request: pb.UploadEvalTableRequest,
) -> pb.UploadEvalTableResponse:
    """Upload an EvalTable to CES through wandb-core and wait for the result.

    Raises:
        CommError: If the upload fails.
    """
    if not run._interface:
        raise UsageError("Cannot upload an EvalTable without a backend.")

    handle = run._interface.deliver_upload_eval_table(request)
    response = handle.wait_or(timeout=None).response.upload_eval_table_response
    if response.error_message:
        raise CommError(f"Failed to upload EvalTable: {response.error_message}")

    return response


class CESWriter:
    """Write an immutable EvalTable through the Evaluations service."""

    def __init__(
        self,
        *,
        unsupported_media_mode: str = "stub",
    ) -> None:
        self._unsupported_media_mode = unsupported_media_mode
        self._bound: _BoundRun | None = None

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None:
        """Validate W&B values before the table is bound or written."""
        if _media_ces.is_supported_wandb_media(value):
            return
        if isinstance(value, WBValue):
            self._validate_wandb_value(value, column)

    def bind_to_run(self, run: LocalRun, key: str) -> None:
        """Bind the run and the history key the table is logged at."""
        if not run.entity or not run.project:
            raise UsageError("CES EvalTable logging requires a W&B entity and project.")
        self._bound = _BoundRun(run=run, eval_table_key=key)

    def write(
        self,
        *,
        name: str,
        rows: Sequence[WriteRow],
        ncols: int,
        log_mode: LogMode,
    ) -> WriteResult:
        """Prepare and persist the CES resources, then return their history value."""
        bound_run = self._require_bound()

        write_payloads = self._build_write_payloads(name=name, rows=rows)
        self._record_media_telemetry(write_payloads)
        if write_payloads.oversized_media_cells:
            locations = ", ".join(write_payloads.oversized_locations)
            wandb.termwarn(
                "EvalTable replaced "
                f"{write_payloads.oversized_media_cells} of "
                f"{write_payloads.media_cells_examined} media cells with null because "
                "their encoded payload reached the "
                f"{_media_ces.CES_MAX_CELL_BYTES / 1_000_000:g} MB limit. "
                f"First affected: {locations}.",
            )

        request = pb.UploadEvalTableRequest(
            name=name,
            dataset_fields=write_payloads.dataset_fields,
            scorers=write_payloads.scorers,
            upload_media_paths=write_payloads.upload_media_paths,
        )
        rows_bytes = sum(row.ByteSize() for row in write_payloads.rows)
        if rows_bytes > _ROWS_FILE_THRESHOLD_BYTES:
            request.rows_file_path = _write_rows_file(write_payloads.rows)
        else:
            request.rows.extend(write_payloads.rows)

        response = _upload_eval_table(bound_run.run, request)

        _logger.debug(
            "CES EvalTable recorded evaluation_version_id=%s",
            response.evaluation_version_id,
        )

        return WriteResult(
            history_value={
                # Frontend dispatches on `_type` and validates the schema version.
                "_type": "eval-table-ces",
                "schema_version": 1,
                "ncols": ncols,
                "nrows": len(rows),
                "log_mode": log_mode,
                "evaluation_id": response.evaluation_id,
                "evaluation_version_id": response.evaluation_version_id,
                "dataset_id": response.dataset_id,
                "dataset_version_id": response.dataset_version_id,
            },
            logged_id=response.evaluation_version_id,
        )

    def _require_bound(self) -> _BoundRun:
        if self._bound is None:
            raise UsageError("EvalTable must be logged with run.log().")
        return self._bound

    def _build_write_payloads(
        self,
        *,
        name: str,
        rows: Sequence[WriteRow],
    ) -> _CESWritePayloads:
        """Validate and normalize rows, infer schemas, and encode the rows."""
        self._validate_name(
            "EvalTable",
            name,
            max_length=_MAX_EVAL_TABLE_NAME_LENGTH,
        )
        if not rows:
            raise UsageError("CES EvalTable logging requires at least one row.")
        if len(rows) > _MAX_ROWS_PER_TABLE:
            raise UsageError(
                "CES EvalTable logging currently supports at most "
                f"{_MAX_ROWS_PER_TABLE} rows per table."
            )

        bound_run = self._require_bound()
        dataset_field_types: dict[tuple[_CESFieldSource, str], _CESFieldType] = {}
        dataset_field_order: dict[tuple[_CESFieldSource, str], None] = {}
        scorer_types: dict[str, PrimitiveValueType] = {}
        scorer_order: dict[str, None] = {}
        normalized_rows: list[_CESRow] = []
        media_cells_examined = 0
        oversized_media_cells = 0
        oversized_locations: list[str] = []
        upload_media_paths: list[str] = []
        class_label_accumulator = _media_ces.ClassLabelAccumulator()

        for row_index, row in enumerate(rows):
            inputs, input_media, input_oversized = (
                self._normalize_row_input_or_output_values(
                    row.inputs,
                    source="input",
                    types=dataset_field_types,
                    order=dataset_field_order,
                    bound_run=bound_run,
                    row_index=row_index,
                    oversized_locations=oversized_locations,
                    upload_media_paths=upload_media_paths,
                    class_label_accumulator=class_label_accumulator,
                )
            )
            media_cells_examined += input_media
            oversized_media_cells += input_oversized
            output = None
            if row.output is not None:
                output, output_media, output_oversized = (
                    self._normalize_row_input_or_output_values(
                        row.output,
                        source="output",
                        types=dataset_field_types,
                        order=dataset_field_order,
                        bound_run=bound_run,
                        row_index=row_index,
                        oversized_locations=oversized_locations,
                        upload_media_paths=upload_media_paths,
                        class_label_accumulator=class_label_accumulator,
                    )
                )
                media_cells_examined += output_media
                oversized_media_cells += output_oversized
            scores = self._normalize_row_score_values(
                row.scores,
                types=scorer_types,
                order=scorer_order,
            )
            normalized_rows.append(
                _ces_row(
                    row_index=row_index,
                    inputs=inputs,
                    output=output,
                    scores=scores,
                )
            )

        missing_fields = [
            column_name
            for source, column_name in dataset_field_order
            if (source, column_name) not in dataset_field_types
        ]
        missing_scorers = [
            column_name
            for column_name in scorer_order
            if column_name not in scorer_types
        ]
        if missing_fields or missing_scorers:
            missing = sorted({*missing_fields, *missing_scorers})
            raise UsageError(
                "Cannot infer primitive types for all-null EvalTable column(s): "
                f"{missing}."
            )

        if len(dataset_field_order) > _MAX_DATASET_FIELDS:
            raise UsageError(
                "CES EvalTable logging supports at most "
                f"{_MAX_DATASET_FIELDS} input and output columns combined."
            )
        if len(scorer_order) > _MAX_SCORERS:
            raise UsageError(
                f"CES EvalTable logging supports at most {_MAX_SCORERS} score columns."
            )

        dataset_fields = [
            dataset_field_types[(source, column_name)].declaration(source, column_name)
            for source, column_name in dataset_field_order
        ]
        scorers = [
            pb.EvalTableScorer(name=column_name, value_type=scorer_types[column_name])
            for column_name in scorer_order
        ]
        encoded_rows = _encode_rows(
            normalized_rows,
            dataset_fields=dataset_fields,
            scorers=scorers,
        )
        class_label_accumulator.flush(bound_run.run)
        return _CESWritePayloads(
            dataset_fields=dataset_fields,
            scorers=scorers,
            rows=encoded_rows,
            upload_media_paths=upload_media_paths,
            media_cells_examined=media_cells_examined,
            oversized_media_cells=oversized_media_cells,
            oversized_locations=tuple(oversized_locations),
        )

    def _normalize_row_input_or_output_values(
        self,
        values: Mapping[ColumnKey, Any],
        *,
        source: _CESFieldSource,
        types: dict[tuple[_CESFieldSource, str], _CESFieldType],
        order: dict[tuple[_CESFieldSource, str], None],
        bound_run: _BoundRun,
        row_index: int,
        oversized_locations: list[str],
        upload_media_paths: list[str],
        class_label_accumulator: _media_ces.ClassLabelAccumulator,
    ) -> tuple[dict[str, Any], int, int]:
        """Normalize one input/output mapping and accumulate its inferred types."""
        normalized_values: dict[str, Any] = {}
        media_cells = 0
        oversized_cells = 0
        for column, value in values.items():
            name = str(column)
            key = (source, name)
            if key not in order:
                self._validate_name(
                    f"{source} column",
                    name,
                    max_length=_MAX_DATASET_FIELD_NAME_LENGTH,
                )
                order[key] = None
            if _media_ces.is_supported_wandb_media(value):
                media_cells += 1
                normalized, value_type, oversized_size = self._normalize_media(
                    value,
                    bound_run,
                    source=source,
                    column_name=name,
                    upload_media_paths=upload_media_paths,
                    class_label_accumulator=class_label_accumulator,
                )
                if oversized_size is not None:
                    oversized_cells += 1
                    if len(oversized_locations) < _MAX_OVERSIZED_MEDIA_LOCATIONS:
                        oversized_locations.append(
                            f"row {row_index}, {source} column {name!r} "
                            f"({oversized_size} bytes)"
                        )
            else:
                normalized, primitive_type = self._normalize_primitive(value, column)
                value_type = (
                    _CESFieldType(primitive_type)
                    if primitive_type is not None
                    else None
                )
            if value_type is not None:
                types[key] = self._merge_field_type(column, types.get(key), value_type)
            normalized_values[name] = normalized
        return normalized_values, media_cells, oversized_cells

    def _normalize_row_score_values(
        self,
        values: Mapping[ColumnKey, Any],
        *,
        types: dict[str, PrimitiveValueType],
        order: dict[str, None],
    ) -> dict[str, Any]:
        """Normalize one score mapping and accumulate its inferred types."""
        normalized_values: dict[str, Any] = {}
        for column, value in values.items():
            name = str(column)
            if name not in order:
                self._validate_name(
                    "score column",
                    name,
                    max_length=_MAX_SCORER_NAME_LENGTH,
                )
                order[name] = None
            if _media_ces.is_supported_wandb_media(value):
                raise UsageError(
                    f"EvalTable score column {column!r} contains unsupported value "
                    f"type {type(value).__name__!r}; only primitive values are supported."
                )
            normalized, value_type = self._normalize_primitive(value, column)
            if value_type is not None:
                types[name] = self._merge_type(column, types.get(name), value_type)
            normalized_values[name] = normalized
        return normalized_values

    def _normalize_media(
        self,
        value: Media,
        bound_run: _BoundRun,
        *,
        source: _CESFieldSource,
        column_name: str,
        upload_media_paths: list[str],
        class_label_accumulator: _media_ces.ClassLabelAccumulator,
    ) -> tuple[Any, _CESFieldType, int | None]:
        """Return W&B media JSON, its field type, and oversized byte count.

        Adds files newly placed in the run's files directory to
        `upload_media_paths`.
        """
        try:
            media_cell = _media_ces.prepare_media(
                value,
                bound_run.run,
                _media_ces.EvalTableMediaField(
                    eval_table_key=bound_run.eval_table_key,
                    source="inputs" if source == "input" else "outputs",
                    column_name=column_name,
                ),
                class_label_accumulator=class_label_accumulator,
            )
        except _media_ces.UnsupportedMediaVariantError as error:
            if self._unsupported_media_mode == "raise":
                raise
            wandb.termwarn(error.stub_warning, repeat=False)
            return (
                None,
                _CESFieldType(
                    value_type="json",
                    media_type=_media_ces.media_type(value),
                ),
                None,
            )
        upload_media_paths.extend(media_cell.new_run_files)
        field_type = _CESFieldType(value_type="json", media_type=media_cell.media_type)
        oversized_size = media_cell.encoded_size if media_cell.oversized else None
        return media_cell.value, field_type, oversized_size

    def _normalize_primitive(
        self,
        value: Any,
        column: ColumnKey,
    ) -> tuple[Any, PrimitiveValueType | None]:
        """Return a JSON-safe value and its observed CES primitive type."""
        if isinstance(value, WBValue):
            value = self._normalize_wandb_value(value, column)
        if value is None:
            return None, None

        np = wandb.util.np
        if isinstance(value, bool) or (np is not None and isinstance(value, np.bool_)):
            return bool(value), "boolean"
        if isinstance(value, int) or (np is not None and isinstance(value, np.integer)):
            normalized = int(value)
            if not _MIN_INT64 <= normalized <= _MAX_INT64:
                raise UsageError(
                    f"CES EvalTable column {column!r} contains an integer outside "
                    "the 64-bit range."
                )
            return normalized, "integer"
        if isinstance(value, float) or (
            np is not None and isinstance(value, np.floating)
        ):
            normalized = float(value)
            if math.isnan(normalized):
                # JSON has no NaN literal; send null while retaining numeric schema.
                return None, "number"
            if not math.isfinite(normalized):
                raise UsageError(
                    f"CES EvalTable column {column!r} contains a non-finite number."
                )
            return normalized, "number"
        if isinstance(value, str) or (np is not None and isinstance(value, np.str_)):
            return str(value), "string"

        raise UsageError(
            f"CES EvalTable column {column!r} contains unsupported value "
            f"type {type(value).__name__!r}; only primitive values are supported."
        )

    def _validate_name(self, kind: str, name: str, *, max_length: int) -> None:
        if not name or len(name) > max_length:
            raise UsageError(
                f"CES {kind} names must contain between 1 and {max_length} "
                f"characters; got {name!r}."
            )

    def _validate_wandb_value(self, value: WBValue, column: ColumnKey) -> None:
        if isinstance(value, Table):
            raise TypeError(
                f"Column {column!r} contains a {type(value).__name__}; "
                "CES EvalTable logging does not support nested Tables."
            )
        if self._unsupported_media_mode == "raise":
            value_kind = "media" if isinstance(value, Media) else "value"
            raise TypeError(
                f"Column {column!r} contains unsupported wandb {value_kind} type "
                f"{type(value).__name__!r}. CES EvalTable logging does not support "
                "wandb media/value types yet. Pass unsupported_media_mode='stub' "
                "to log a placeholder string instead."
            )

    def _normalize_wandb_value(self, value: WBValue, column: ColumnKey) -> str:
        """Validate or replace an unsupported W&B value with a placeholder."""
        # Keep media adaptation behind one hook so CES-native media can replace
        # the unsupported fallback as its schemas and upload paths are added.
        self._validate_wandb_value(value, column)
        wandb.termwarn(
            f"wandb.{type(value).__name__} values are not yet supported by CES "
            "EvalTable logging. They will be logged as placeholder strings.",
            repeat=False,
        )
        return f"[wandb.{type(value).__name__} not yet supported]"

    def _merge_type(
        self,
        column: ColumnKey,
        existing: PrimitiveValueType | None,
        observed: PrimitiveValueType,
    ) -> PrimitiveValueType:
        """Merge observed types, widening integer and number columns to number."""
        if existing is None or existing == observed:
            return observed
        if {existing, observed} == {"integer", "number"}:
            return "number"
        # An explicit permissive dtype can bypass Table's usual type check.
        raise UsageError(
            f"CES EvalTable column {column!r} mixes {existing!r} and "
            f"{observed!r} values."
        )

    def _merge_field_type(
        self,
        column: ColumnKey,
        existing: _CESFieldType | None,
        observed: _CESFieldType,
    ) -> _CESFieldType:
        if existing is None or existing == observed:
            return observed
        if (
            existing.media_type is None
            and observed.media_type is None
            and existing.value_type != "json"
            and observed.value_type != "json"
        ):
            return _CESFieldType(
                self._merge_type(
                    column,
                    existing.value_type,
                    observed.value_type,
                )
            )
        existing_type = existing.media_type or existing.value_type
        observed_type = observed.media_type or observed.value_type
        raise UsageError(
            f"EvalTable column {column!r} mixes {existing_type!r} and "
            f"{observed_type!r} values."
        )

    def _record_media_telemetry(self, prepared: _CESWritePayloads) -> None:
        # Track whether cells above 3.5 MB justify extended media metadata support.
        if prepared.media_cells_examined == 0:
            return

        recorder = get_telemetry_recorder()
        recorder.increment_counter(
            "eval_table_ces_media_write",
            LowCardinalityAttributes(),
        )
        if prepared.oversized_media_cells:
            recorder.increment_counter(
                "eval_table_ces_media_write_with_oversized_cells",
                LowCardinalityAttributes(),
            )
