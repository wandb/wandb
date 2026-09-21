from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import wandb
from wandb.apis.public.service_api import ServiceApi
from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import Media
from wandb.sdk.data_types.base_types.wb_value import WBValue
from wandb.sdk.data_types.eval_table._writer import WriteInput, WriteResult
from wandb.sdk.data_types.table import Table

if TYPE_CHECKING:
    from coreweave_evaluations import CoreWeaveEvaluations as CoreWeaveEvaluationsT

    from wandb.sdk.data_types.table import ColumnKey
    from wandb.sdk.wandb_run import Run as LocalRun


_logger = logging.getLogger(__name__)

_CES_BASE_URL_ENV = "CES_BASE_URL"
_WANDB_SCOPE_NAMESPACE = "wandb"
_PROJECT_SCOPE_QUERY = """
query EvalTableProjectScope($entity: String!, $project: String!) {
  project(entityName: $entity, name: $project) {
    internalId
  }
}
"""


def _encode_json(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


# Server request-body limit.
_MAX_REQUEST_BODY_BYTES = 16 << 20
_MAX_REQUEST_BODY_SIZE = "16 MiB"
# These two shape each `rows-{i}` body. If either changes, bump the idempotency-key
# version so retries of partially uploaded tables cannot reuse keys across layouts.
# The byte target leaves headroom below the hard request limit.
_TARGET_ROW_BATCH_BODY_BYTES = 8 << 20
_MAX_ROWS_PER_BATCH = 10_000
# Evaluations request-schema limits.
_MAX_DATASET_FIELDS = 10_000
_MAX_DATASET_FIELD_NAME_LENGTH = 512
_MAX_EVAL_TABLE_NAME_LENGTH = 256
# Allow ten count-limited batches while failing fast on runaway tables.
_MAX_ROWS_PER_TABLE = 100_000
_MAX_SCORERS = 256
_MAX_SCORER_NAME_LENGTH = 256

# Bytes in an add_rows body other than encoded rows and their separating commas.
_ROW_BATCH_ENVELOPE_BYTES = len(_encode_json({"rows": []}))

PrimitiveValueType = Literal["boolean", "integer", "number", "string"]
_CESRow = dict[str, Any]


def _iter_row_batches(
    rows: Sequence[_CESRow],
    *,
    max_body_bytes: int,
    target_body_bytes: int,
    max_rows: int,
) -> Iterator[list[_CESRow]]:
    batch: list[_CESRow] = []
    batch_size = _ROW_BATCH_ENVELOPE_BYTES

    for row_index, row in enumerate(rows):
        row_size = len(_encode_json(row))
        if _ROW_BATCH_ENVELOPE_BYTES + row_size >= max_body_bytes:
            raise UsageError(
                "CES EvalTable rows payload contains a row at index "
                f"{row_index} whose encoded request must be smaller than "
                f"{_MAX_REQUEST_BODY_SIZE}."
            )

        # An above-target batch contains exactly one row, which already passed
        # the hard request-size check; the next row flushes it here.
        if batch and (
            len(batch) >= max_rows or batch_size + 1 + row_size > target_body_bytes
        ):
            yield batch
            batch, batch_size = [], _ROW_BATCH_ENVELOPE_BYTES

        batch_size += row_size + (1 if batch else 0)
        batch.append(row)

    if batch:
        yield batch


@dataclass(frozen=True)
class _CESWritePayloads:
    dataset_fields: list[dict[str, str]]
    scorers: list[dict[str, str]]
    row_batches: list[list[_CESRow]]


@dataclass(frozen=True)
class _CESScopeContext:
    scope_ref: str
    api_key: str | None = field(repr=False)
    access_token: str | None = field(repr=False)


@dataclass(frozen=True)
class _BoundRun:
    entity: str
    project: str
    service_api: ServiceApi
    idempotency_scope: str


class CESWriter:
    """Write an immutable EvalTable through the Evaluations service."""

    def __init__(
        self,
        *,
        service_api: ServiceApi | None = None,
        unsupported_media_mode: str = "stub",
    ) -> None:
        self._service_api = service_api
        self._unsupported_media_mode = unsupported_media_mode
        self._bound: _BoundRun | None = None

    def bind_to_run(self, run: LocalRun, key: str, step: int | str) -> None:
        """Bind the run and derive a stable retry identity for this log location."""
        if not run.entity or not run.project:
            raise UsageError("CES EvalTable logging requires a W&B entity and project.")
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
        self._bound = _BoundRun(
            entity=run.entity,
            project=run.project,
            service_api=self._service_api or ServiceApi(run._settings),
            idempotency_scope=hashlib.sha256(identity.encode()).hexdigest(),
        )

    def validate_cell_value(self, value: Any, column: ColumnKey) -> None:
        """Reject unsupported W&B values before the table is bound or written."""
        if isinstance(value, WBValue):
            self._validate_wandb_value(value, column)

    def write(self, payload: WriteInput) -> WriteResult:
        """Prepare and persist the CES resources, then return their history marker."""
        bound_run = self._require_bound()

        base_url = os.environ.get(_CES_BASE_URL_ENV)
        if not base_url:
            raise UsageError(
                f"Set {_CES_BASE_URL_ENV} to the Evaluations service URL "
                "before logging a CES EvalTable."
            )

        # TODO: coreweave_evaluations is new and under development. This will become
        # obsolete once we actually publish the package and add it to wandb deps.
        try:
            from coreweave_evaluations import CoreWeaveEvaluations
        except ImportError as exc:
            raise UsageError(
                "CES EvalTable logging requires the coreweave_evaluations package."
            ) from exc

        write_payloads = self._build_write_payloads(payload)
        scope = self._resolve_scope_context(bound_run)
        client = self._create_client(CoreWeaveEvaluations, base_url, scope)
        try:
            created = client.eval_tables.create(
                scope.scope_ref,
                namespace=_WANDB_SCOPE_NAMESPACE,
                name=payload.name,
                idempotency_key=self._idempotency_key(bound_run, "create"),
            )
            client.eval_tables.create_columns(
                created.evaluation_id,
                namespace=_WANDB_SCOPE_NAMESPACE,
                scope_ref=scope.scope_ref,
                dataset_fields=write_payloads.dataset_fields,
                scorers=write_payloads.scorers,
                idempotency_key=self._idempotency_key(bound_run, "columns"),
            )
            for batch_index, rows in enumerate(write_payloads.row_batches):
                client.eval_tables.add_rows(
                    created.evaluation_id,
                    namespace=_WANDB_SCOPE_NAMESPACE,
                    scope_ref=scope.scope_ref,
                    rows=rows,
                    idempotency_key=self._idempotency_key(
                        bound_run, f"rows-{batch_index}"
                    ),
                )
            version = client.eval_tables.create_version(
                created.evaluation_id,
                namespace=_WANDB_SCOPE_NAMESPACE,
                scope_ref=scope.scope_ref,
                idempotency_key=self._idempotency_key(bound_run, "version"),
            )
        finally:
            client.close()

        _logger.debug(
            "CES EvalTable recorded namespace=%s scope_ref=%s evaluation_version_id=%s",
            _WANDB_SCOPE_NAMESPACE,
            scope.scope_ref,
            version.evaluation_version_id,
        )

        return WriteResult(
            marker={
                # Frontend dispatches on `_type` and validates the schema version.
                "_type": "eval-table-ces",
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

    def _build_write_payloads(self, value: WriteInput) -> _CESWritePayloads:
        """Normalize rows and infer ordered column schemas."""
        self._validate_name(
            "EvalTable",
            value.name,
            max_length=_MAX_EVAL_TABLE_NAME_LENGTH,
        )
        if not value.rows:
            raise UsageError("CES EvalTable logging requires at least one row.")
        if len(value.rows) > _MAX_ROWS_PER_TABLE:
            raise UsageError(
                "CES EvalTable logging currently supports at most "
                f"{_MAX_ROWS_PER_TABLE} rows per table."
            )

        dataset_field_types: dict[tuple[str, str], PrimitiveValueType] = {}
        dataset_field_order: dict[tuple[str, str], None] = {}
        scorer_types: dict[str, PrimitiveValueType] = {}
        scorer_order: dict[str, None] = {}
        rows: list[_CESRow] = []

        for row in value.rows:
            inputs = self._normalize_row_input_or_output_values(
                row.inputs,
                source="input",
                column_keys=value.column_keys,
                types=dataset_field_types,
                order=dataset_field_order,
            )
            outputs = (
                self._normalize_row_input_or_output_values(
                    row.outputs,
                    source="output",
                    column_keys=value.column_keys,
                    types=dataset_field_types,
                    order=dataset_field_order,
                )
                if row.outputs is not None
                else None
            )
            scores = self._normalize_row_score_values(
                row.scores,
                column_keys=value.column_keys,
                types=scorer_types,
                order=scorer_order,
            )
            rows.append({"input": inputs, "output": outputs, "scores": scores})

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
                f"{_MAX_DATASET_FIELDS} input and output columns combined."
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
        return _CESWritePayloads(
            dataset_fields=dataset_fields,
            scorers=scorers,
            # Materialize batches so every size error precedes the first request.
            row_batches=list(
                _iter_row_batches(
                    rows,
                    max_body_bytes=_MAX_REQUEST_BODY_BYTES,
                    target_body_bytes=_TARGET_ROW_BATCH_BODY_BYTES,
                    max_rows=_MAX_ROWS_PER_BATCH,
                )
            ),
        )

    def _normalize_row_input_or_output_values(
        self,
        values: Mapping[str, Any],
        *,
        source: Literal["input", "output"],
        column_keys: Mapping[str, ColumnKey],
        types: dict[tuple[str, str], PrimitiveValueType],
        order: dict[tuple[str, str], None],
    ) -> dict[str, Any]:
        """Normalize one input/output mapping and accumulate its inferred types."""
        normalized_values: dict[str, Any] = {}
        for name, value in values.items():
            key = (source, name)
            if key not in order:
                self._validate_name(
                    f"{source} column",
                    name,
                    max_length=_MAX_DATASET_FIELD_NAME_LENGTH,
                )
                order[key] = None
            column = column_keys.get(name, name)
            normalized, value_type = self._normalize_primitive(value, column)
            if value_type is not None:
                types[key] = self._merge_type(column, types.get(key), value_type)
            normalized_values[name] = normalized
        return normalized_values

    def _normalize_row_score_values(
        self,
        values: Mapping[str, Any],
        *,
        column_keys: Mapping[str, ColumnKey],
        types: dict[str, PrimitiveValueType],
        order: dict[str, None],
    ) -> dict[str, Any]:
        """Normalize one score mapping and accumulate its inferred types."""
        normalized_values: dict[str, Any] = {}
        for name, value in values.items():
            if name not in order:
                self._validate_name(
                    "score column",
                    name,
                    max_length=_MAX_SCORER_NAME_LENGTH,
                )
                order[name] = None
            column = column_keys.get(name, name)
            normalized, value_type = self._normalize_primitive(value, column)
            if value_type is not None:
                types[name] = self._merge_type(column, types.get(name), value_type)
            normalized_values[name] = normalized
        return normalized_values

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

    def _validate_body_size(self, operation: str, body: dict[str, Any]) -> None:
        """Reject a request body at or above the CES hard limit."""
        if len(_encode_json(body)) >= _MAX_REQUEST_BODY_BYTES:
            raise UsageError(
                f"CES EvalTable {operation} payload must be smaller than "
                f"{_MAX_REQUEST_BODY_SIZE}."
            )

    def _require_bound(self) -> _BoundRun:
        if self._bound is None:
            raise UsageError("EvalTable must be logged with run.log().")
        return self._bound

    def _idempotency_key(self, bound_run: _BoundRun, operation: str) -> str:
        """Derive an operation-specific retry key from the bound log location."""
        return f"wandb-eval-table-v1-{bound_run.idempotency_scope}-{operation}"

    def _resolve_scope_context(self, bound_run: _BoundRun) -> _CESScopeContext:
        """Resolve the project scope and preferred run credential for CES."""
        response = bound_run.service_api.execute_graphql(
            _PROJECT_SCOPE_QUERY,
            variables={"entity": bound_run.entity, "project": bound_run.project},
        )
        project = response.get("project") if isinstance(response, dict) else None
        scope_ref = project.get("internalId") if isinstance(project, dict) else None
        if not isinstance(scope_ref, str) or not scope_ref:
            raise UsageError(
                f"Unable to resolve W&B project {bound_run.entity}/{bound_run.project}."
            )

        api_key = bound_run.service_api.api_key
        access_token = None if api_key else bound_run.service_api.access_token()
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
        client_type: type[CoreWeaveEvaluationsT],
        base_url: str,
        scope: _CESScopeContext,
    ) -> CoreWeaveEvaluationsT:
        """Create a client while keeping the run's credentials authoritative."""
        # The client builds the Authorization header from these and rejects a
        # request that reaches it without one, so a header set on an httpx
        # client would arrive too late to satisfy it.
        client = client_type(
            base_url=base_url,
            api_key=scope.api_key,
            bearer_token=scope.access_token,
        )
        # The generated constructor fills None credentials from the environment.
        # Keep the run's resolved choice authoritative when both are present.
        client.api_key = scope.api_key
        client.bearer_token = scope.access_token
        return client
