from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

import wandb
import wandb.integration.weave as weave_integration
import wandb.integration.weave.media_adapters as media_adapters
from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import Media, _numpy_arrays_to_lists
from wandb.sdk.data_types.base_types.wb_value import WBValue
from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    from wandb.apis.public.service_api import ServiceApi
    from wandb.sdk.data_types.table import ColumnKey, LogMode
    from wandb.sdk.wandb_run import Run as LocalRun


_logger = logging.getLogger(__name__)

EVAL_TABLE_MARKER = {"wandb_eval_table": True}

_MIN_WEAVE_VERSION = "0.52.41"
_CES_BASE_URL_ENV = "CES_BASE_URL"
_WANDB_SCOPE_NAMESPACE = "wandb"
_PROJECT_SCOPE_QUERY = """
query EvalTableProjectScope($entity: String!, $project: String!) {
  project(entityName: $entity, name: $project) {
    internalId
  }
}
"""
# These match the service request-schema limits.
_MAX_BATCH_BODY_BYTES = 16 << 20
# Leave headroom below the server limit and keep failed retries bounded.
_TARGET_ROW_BATCH_BODY_BYTES = 8 << 20
_MAX_DATASET_FIELDS = 10_000
_MAX_DATASET_FIELD_NAME_LENGTH = 512
_MAX_EVAL_TABLE_NAME_LENGTH = 256
_MAX_ROWS_PER_BATCH = 10_000
_MAX_ROWS = 100_000
_MAX_SCORERS = 256
_MAX_SCORER_NAME_LENGTH = 256

_ROW_BATCH_PREFIX_BYTES = len(b'{"rows":[')
_ROW_BATCH_SUFFIX_BYTES = len(b"]}")

EvalTableBackend = Literal["weave", "ces"]
PrimitiveValueType = Literal["boolean", "integer", "number", "string"]


def _load_ces_client_type() -> Any:
    # This generated optional dependency is absent from the SDK type-check env.
    try:
        from coreweave_evaluations import CoreWeaveEvaluations
    except ImportError as exc:
        raise UsageError(
            "CES EvalTable logging requires the coreweave_evaluations "
            "package, which wandb/core generates and does not publish. Install "
            "it from core/services/evaluations/generated/python; the venv-dev "
            "target in examples-dev/evals-for-models builds an environment "
            "with it."
        ) from exc

    return CoreWeaveEvaluations


@dataclass(frozen=True, kw_only=True)
class EvalTableWriteRow:
    inputs: Mapping[str, Any]
    output: Mapping[str, Any] | None
    scores: Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class EvalTableWriteInput:
    name: str
    rows: Sequence[EvalTableWriteRow]
    column_keys: Mapping[str, ColumnKey]
    ncols: int
    log_mode: LogMode


@dataclass(frozen=True, kw_only=True)
class EvalTableWriteResult:
    """Backend-owned run-history marker and its backend-specific identifier.

    Writers return complete, intentionally separate marker formats rather than
    sharing an envelope; for example, Weave uses `_type: "eval-table"` while
    CES uses `_type: "eval-table-ces"`.
    """

    marker: Mapping[str, Any]
    logged_id: str


class EvalTableWriter(Protocol):
    """Persist one EvalTable and return its backend-owned history marker.

    `validate_cell_value` may run before `bind` while Table constructs its rows.
    `bind` establishes the run context and precedes `write`. A successful write
    is cached, while a failed write may be retried. `logged_id` identifies the
    evaluation written by the selected backend.
    """

    def bind(self, run: LocalRun, key: str, step: int | str) -> None: ...

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None: ...

    def write(self, payload: EvalTableWriteInput) -> EvalTableWriteResult: ...


def create_eval_table_writer(
    backend: EvalTableBackend,
    *,
    allow_mixed_types: bool,
    unsupported_media_mode: media_adapters.UnsupportedMediaMode,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    if backend == "ces":
        if allow_mixed_types:
            raise UsageError("CES EvalTable logging requires allow_mixed_types=False.")
        return CESEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    raise UsageError(
        f"Unsupported EvalTable backend {backend!r}; expected 'weave' or 'ces'."
    )


def _is_numpy_datetime64(value: Any) -> bool:
    # Optional import: only imports NumPy if it is already installed.
    np = wandb.util.np
    return np is not None and isinstance(value, np.datetime64)


def _is_datetime_like(value: Any) -> bool:
    return isinstance(value, datetime.date) or _is_numpy_datetime64(value)


def _normalize_numpy_datetime64(value: Any) -> datetime.datetime | None:
    # NumPy only converts to Python datetime at microsecond resolution; ns and
    # finer units otherwise become raw integer offsets.
    py_value = value.astype("datetime64[us]").tolist()
    if py_value is None:
        return None
    if isinstance(py_value, datetime.datetime):
        return py_value.replace(tzinfo=datetime.timezone.utc)
    if isinstance(py_value, datetime.date):
        return datetime.datetime(
            py_value.year,
            py_value.month,
            py_value.day,
            tzinfo=datetime.timezone.utc,
        )

    raise TypeError(f"Unexpected numpy.datetime64 conversion result: {py_value!r}")


def _normalize_datetime(value: Any) -> datetime.datetime | None:
    """Normalize datetime-like values for Weave; NumPy NaT becomes None."""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        # Weave handles datetime.datetime but not datetime.date.
        return datetime.datetime(
            value.year,
            value.month,
            value.day,
            tzinfo=datetime.timezone.utc,
        )

    return _normalize_numpy_datetime64(value)


def _normalize_non_media_value(value: Any) -> Any:
    if _is_datetime_like(value):
        return _normalize_datetime(value)

    value = _numpy_arrays_to_lists(value)

    # Normalize scalar NumPy values and other simple values like Table does.
    value, _ = wandb.util.json_friendly(value)

    if isinstance(value, dict):
        return {key: _normalize_non_media_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_non_media_value(item) for item in value]

    return value


class WeaveEvalTableWriter:
    def __init__(
        self,
        *,
        unsupported_media_mode: media_adapters.UnsupportedMediaMode,
    ) -> None:
        weave_integration.ensure_version(
            _MIN_WEAVE_VERSION,
            'EvalTable dependency error. Fix with: `pip install wandb["eval-table"]`.',
        )
        media_adapters.validate_unsupported_media_mode(unsupported_media_mode)
        self._unsupported_media_mode = unsupported_media_mode

    def bind(self, run: LocalRun, key: str, step: int | str) -> None:
        # Other writers use run/key/step to derive stable idempotency keys, so
        # keep the full logging location in the shared protocol.
        del key, step
        weave_integration.init_weave(run.entity, run.project)

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None:
        media_adapters.validate_supported_value(
            value,
            column,
            unsupported_media_mode=self._unsupported_media_mode,
        )

    def write(self, payload: EvalTableWriteInput) -> EvalTableWriteResult:
        from weave.evaluation.eval_imperative import EvaluationLogger

        evaluation = EvaluationLogger._create_with_meta(
            EVAL_TABLE_MARKER,
            name=payload.name,
        )
        for row in payload.rows:
            evaluation.log_example(
                inputs=self._normalize_mapping(row.inputs, payload.column_keys),
                output=(
                    self._normalize_mapping(row.output, payload.column_keys)
                    if row.output is not None
                    else None
                ),
                scores=self._normalize_mapping(row.scores, payload.column_keys),
            )

        evaluation.log_summary()
        # TODO: We should work with Weave on exposing a public evaluate_call_id()
        # instead of relying on this private field.
        evaluate_call_id = evaluation._evaluate_call.id
        return EvalTableWriteResult(
            marker={
                "_type": "eval-table",
                "ncols": payload.ncols,
                "nrows": len(payload.rows),
                "log_mode": payload.log_mode,
                "evaluate_call_id": evaluate_call_id,
            },
            logged_id=evaluate_call_id,
        )

    def _normalize_mapping(
        self,
        values: Mapping[str, Any],
        column_keys: Mapping[str, ColumnKey],
    ) -> dict[str, Any]:
        return {
            column: self._normalize_value(item, column_keys.get(column, column))
            for column, item in values.items()
        }

    def _normalize_value(self, value: Any, column: ColumnKey) -> Any:
        """Adapt media, then apply Table-like normalization for plain values.

        TODO: Media stubbing is temporary until every backend supports these values.
        """
        value = media_adapters.unwrap_value(
            value,
            column,
            unsupported_media_mode=self._unsupported_media_mode,
        )
        value = media_adapters.handle_nested_wandb_values(
            value,
            column,
            self._unsupported_media_mode,
        )
        return _normalize_non_media_value(value)


@dataclass(frozen=True)
class _PreparedCESWrite:
    dataset_fields: list[dict[str, str]]
    scorers: list[dict[str, str]]
    row_batches: list[list[dict[str, Any]]]


@dataclass(frozen=True)
class _CESScopeContext:
    scope_ref: str
    api_key: str | None = field(repr=False)
    access_token: str | None = field(repr=False)


class CESEvalTableWriter:
    """Write an immutable EvalTable through the Evaluations service."""

    def __init__(
        self,
        *,
        unsupported_media_mode: media_adapters.UnsupportedMediaMode = "stub",
    ) -> None:
        media_adapters.validate_unsupported_media_mode(unsupported_media_mode)
        self._unsupported_media_mode = unsupported_media_mode
        self._entity: str | None = None
        self._project: str | None = None
        self._service_api: ServiceApi | None = None
        self._idempotency_scope: str | None = None

    def bind(self, run: LocalRun, key: str, step: int | str) -> None:
        from wandb.apis.public.service_api import ServiceApi

        if not run.entity or not run.project:
            raise UsageError("CES EvalTable logging requires a W&B entity and project.")
        self._entity = run.entity
        self._project = run.project
        self._service_api = ServiceApi(run._settings)
        # CES replays the same key and body, but rejects a reused key whose body
        # differs, so a logging location is a stable retry identity, not an update.
        identity = json.dumps(
            {
                "entity": run.entity,
                "project": run.project,
                "run_id": run.id,
                "history_key": key,
                "step": str(step),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self._idempotency_scope = hashlib.sha256(identity.encode()).hexdigest()

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None:
        if isinstance(value, WBValue):
            self._validate_wandb_value(value, column)
            return
        # Normalize here only for its construction-time validation errors.
        self._normalize_primitive(value, column)

    def write(self, payload: EvalTableWriteInput) -> EvalTableWriteResult:
        if self._entity is None or self._project is None or self._service_api is None:
            raise UsageError("EvalTable must be logged with run.log().")

        base_url = os.environ.get(_CES_BASE_URL_ENV)
        if not base_url:
            raise UsageError(
                f"Set {_CES_BASE_URL_ENV} to the Evaluations service URL "
                "before logging a CES EvalTable."
            )

        client_type = _load_ces_client_type()
        prepared = self._prepare(payload)
        scope = self._resolve_scope_context()
        client = self._create_client(client_type, base_url, scope)
        try:
            created = client.eval_tables.create(
                scope.scope_ref,
                namespace=_WANDB_SCOPE_NAMESPACE,
                name=payload.name,
                idempotency_key=self._idempotency_key("create"),
            )
            client.eval_tables.create_columns(
                created.evaluation_id,
                namespace=_WANDB_SCOPE_NAMESPACE,
                scope_ref=scope.scope_ref,
                dataset_fields=prepared.dataset_fields,
                scorers=prepared.scorers,
                idempotency_key=self._idempotency_key("columns"),
            )
            for batch_index, rows in enumerate(prepared.row_batches):
                client.eval_tables.add_rows(
                    created.evaluation_id,
                    namespace=_WANDB_SCOPE_NAMESPACE,
                    scope_ref=scope.scope_ref,
                    rows=rows,
                    idempotency_key=self._idempotency_key(f"rows-{batch_index}"),
                )
            version = client.eval_tables.create_version(
                created.evaluation_id,
                namespace=_WANDB_SCOPE_NAMESPACE,
                scope_ref=scope.scope_ref,
                idempotency_key=self._idempotency_key("version"),
            )
        finally:
            client.close()

        _logger.debug(
            "CES EvalTable recorded namespace=%s scope_ref=%s evaluation_version_id=%s",
            _WANDB_SCOPE_NAMESPACE,
            scope.scope_ref,
            version.evaluation_version_id,
        )

        return EvalTableWriteResult(
            marker={
                # Frontend dispatches on `_type` and validates backend/schema.
                "_type": "eval-table-ces",
                "backend": "ces",
                "schema_version": 1,
                "ncols": payload.ncols,
                "nrows": len(payload.rows),
                "log_mode": payload.log_mode,
                "evaluation_id": created.evaluation_id,
                "evaluation_version_id": version.evaluation_version_id,
                "dataset_id": created.dataset_id,
                "dataset_version_id": version.dataset_version_id,
            },
            logged_id=version.evaluation_version_id,
        )

    def _prepare(self, value: EvalTableWriteInput) -> _PreparedCESWrite:
        self._validate_name(
            "EvalTable",
            value.name,
            max_length=_MAX_EVAL_TABLE_NAME_LENGTH,
        )
        if not value.rows:
            raise UsageError("CES EvalTable logging requires at least one row.")
        if len(value.rows) > _MAX_ROWS:
            raise UsageError(
                f"CES EvalTable logging currently supports at most {_MAX_ROWS} "
                "rows per table."
            )

        dataset_field_types: dict[tuple[str, str], PrimitiveValueType] = {}
        dataset_field_order: dict[tuple[str, str], None] = {}
        scorer_types: dict[str, PrimitiveValueType] = {}
        scorer_order: dict[str, None] = {}
        rows: list[dict[str, Any]] = []

        for row in value.rows:
            inputs = self._prepare_mapping(
                row.inputs,
                source="input",
                column_keys=value.column_keys,
                types=dataset_field_types,
                order=dataset_field_order,
            )
            output = (
                self._prepare_mapping(
                    row.output,
                    source="output",
                    column_keys=value.column_keys,
                    types=dataset_field_types,
                    order=dataset_field_order,
                )
                if row.output is not None
                else None
            )
            scores = self._prepare_scores(
                row.scores,
                column_keys=value.column_keys,
                types=scorer_types,
                order=scorer_order,
            )
            rows.append({"input": inputs, "output": output, "scores": scores})

        missing_fields = [
            name
            for source, name in dataset_field_order
            if (source, name) not in dataset_field_types
        ]
        missing_scorers = [name for name in scorer_order if name not in scorer_types]
        if missing_fields or missing_scorers:
            missing = sorted({*missing_fields, *missing_scorers})
            raise UsageError(
                "Cannot infer primitive types for all-null EvalTable column(s): "
                f"{missing}."
            )

        if len(dataset_field_order) > _MAX_DATASET_FIELDS:
            raise UsageError(
                "CES EvalTable logging supports at most "
                f"{_MAX_DATASET_FIELDS} Dataset fields."
            )
        if len(scorer_order) > _MAX_SCORERS:
            raise UsageError(
                f"CES EvalTable logging supports at most {_MAX_SCORERS} score columns."
            )

        dataset_fields = [
            {
                "source": source,
                "name": name,
                "value_type": dataset_field_types[(source, name)],
            }
            for source, name in dataset_field_order
        ]
        scorers = [
            {"name": name, "value_type": scorer_types[name]} for name in scorer_order
        ]
        self._validate_body_size(
            "columns", {"dataset_fields": dataset_fields, "scorers": scorers}
        )
        return _PreparedCESWrite(
            dataset_fields=dataset_fields,
            scorers=scorers,
            row_batches=list(self._iter_row_batches(rows)),
        )

    def _iter_row_batches(
        self,
        rows: list[dict[str, Any]],
    ) -> Iterator[list[dict[str, Any]]]:
        batch: list[dict[str, Any]] = []
        batch_size = _ROW_BATCH_PREFIX_BYTES + _ROW_BATCH_SUFFIX_BYTES

        for row_index, row in enumerate(rows):
            row_size = len(self._encode_json(row))
            single_row_body_size = (
                _ROW_BATCH_PREFIX_BYTES + row_size + _ROW_BATCH_SUFFIX_BYTES
            )
            if single_row_body_size >= _MAX_BATCH_BODY_BYTES:
                raise UsageError(
                    "CES EvalTable rows payload contains a row at index "
                    f"{row_index} whose encoded request must be smaller than 16 MiB."
                )

            separator_size = 1 if batch else 0
            # An above-target batch can only contain one row, which already passed
            # the hard 16 MiB check; later rows flush it before they are appended.
            if batch and (
                len(batch) >= _MAX_ROWS_PER_BATCH
                or batch_size + separator_size + row_size > _TARGET_ROW_BATCH_BODY_BYTES
            ):
                yield batch
                batch = []
                batch_size = _ROW_BATCH_PREFIX_BYTES + _ROW_BATCH_SUFFIX_BYTES
                separator_size = 0

            batch.append(row)
            batch_size += separator_size + row_size

        if batch:
            yield batch

    def _prepare_mapping(
        self,
        values: Mapping[str, Any],
        *,
        source: Literal["input", "output"],
        column_keys: Mapping[str, ColumnKey],
        types: dict[tuple[str, str], PrimitiveValueType],
        order: dict[tuple[str, str], None],
    ) -> dict[str, Any]:
        prepared: dict[str, Any] = {}
        for name, value in values.items():
            key = (source, name)
            if key not in order:
                self._validate_name(
                    "Dataset field",
                    name,
                    max_length=_MAX_DATASET_FIELD_NAME_LENGTH,
                )
                order[key] = None
            column = column_keys.get(name, name)
            normalized, value_type = self._normalize_primitive(value, column)
            if value_type is not None:
                types[key] = self._merge_type(column, types.get(key), value_type)
            prepared[name] = normalized
        return prepared

    def _prepare_scores(
        self,
        values: Mapping[str, Any],
        *,
        column_keys: Mapping[str, ColumnKey],
        types: dict[str, PrimitiveValueType],
        order: dict[str, None],
    ) -> dict[str, Any]:
        prepared: dict[str, Any] = {}
        for name, value in values.items():
            if name not in order:
                self._validate_name(
                    "Scorer",
                    name,
                    max_length=_MAX_SCORER_NAME_LENGTH,
                )
                order[name] = None
            column = column_keys.get(name, name)
            normalized, value_type = self._normalize_primitive(value, column)
            if value_type is not None:
                types[name] = self._merge_type(column, types.get(name), value_type)
            prepared[name] = normalized
        return prepared

    def _normalize_primitive(
        self,
        value: Any,
        column: ColumnKey,
    ) -> tuple[Any, PrimitiveValueType | None]:
        if isinstance(value, WBValue):
            value = self._normalize_wandb_value(value, column)
        if value is None:
            return None, None

        np = wandb.util.np
        if isinstance(value, bool) or (np is not None and isinstance(value, np.bool_)):
            return bool(value), "boolean"
        if isinstance(value, int) or (np is not None and isinstance(value, np.integer)):
            return int(value), "integer"
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
        if existing is None or existing == observed:
            return observed
        if {existing, observed} == {"integer", "number"}:
            return "number"
        # An explicit permissive dtype can bypass Table's usual type check.
        raise UsageError(
            f"CES EvalTable column {column!r} mixes {existing!r} and "
            f"{observed!r} values."
        )

    def _validate_body_size(self, operation: str, body: dict[str, Any]) -> None:
        if len(self._encode_json(body)) >= _MAX_BATCH_BODY_BYTES:
            raise UsageError(
                f"CES EvalTable {operation} payload must be smaller than 16 MiB."
            )

    def _encode_json(self, value: Any) -> bytes:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()

    def _idempotency_key(self, operation: str) -> str:
        if self._idempotency_scope is None:
            raise UsageError("EvalTable must be logged with run.log().")
        return f"wandb-eval-table-v1-{self._idempotency_scope}-{operation}"

    def _resolve_scope_context(self) -> _CESScopeContext:
        if self._entity is None or self._project is None or self._service_api is None:
            raise UsageError("EvalTable must be logged with run.log().")

        response = self._service_api.execute_graphql(
            _PROJECT_SCOPE_QUERY,
            variables={"entity": self._entity, "project": self._project},
        )
        project = response.get("project") if isinstance(response, dict) else None
        scope_ref = project.get("internalId") if isinstance(project, dict) else None
        if not isinstance(scope_ref, str) or not scope_ref:
            raise UsageError(
                f"Unable to resolve W&B project {self._entity}/{self._project}."
            )

        api_key = self._service_api.api_key
        access_token = None if api_key else self._service_api.access_token()
        if not api_key and not access_token:
            raise UsageError(
                "CES EvalTable logging requires authenticated W&B credentials."
            )

        return _CESScopeContext(
            scope_ref=scope_ref,
            api_key=api_key,
            access_token=access_token,
        )

    def _create_client(
        self,
        client_type: Any,
        base_url: str,
        scope: _CESScopeContext,
    ) -> Any:
        # The client builds the Authorization header from these and rejects a
        # request that reaches it without one, so a header set on an httpx
        # client would arrive too late to satisfy it. A None credential may be
        # filled from the client's environment; bearer auth wins if both exist.
        return client_type(
            base_url=base_url,
            api_key=scope.api_key,
            bearer_token=scope.access_token,
        )
