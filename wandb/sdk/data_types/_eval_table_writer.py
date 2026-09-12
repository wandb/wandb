from __future__ import annotations

import datetime
import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

import wandb
import wandb.integration.weave as weave_integration
import wandb.integration.weave.media_adapters as media_adapters
from wandb.errors import UsageError
from wandb.sdk.data_types.base_types.media import _numpy_arrays_to_lists

if TYPE_CHECKING:
    from wandb.sdk.wandb_run import Run as LocalRun


_logger = logging.getLogger(__name__)

EVAL_TABLE_MARKER = {"wandb_eval_table": True}

_MIN_WEAVE_VERSION = "0.52.41"
_COREWEAVE_BASE_URL_ENV = "COREWEAVE_EVALUATIONS_BASE_URL"
_MAX_BATCH_BODY_BYTES = 16 << 20
_MAX_DATASET_FIELDS = 10_000
_MAX_ROWS = 10_000
_MAX_SCORERS = 256

EvalTableBackend = Literal["weave", "coreweave"]
PrimitiveValueType = Literal["boolean", "integer", "number", "string"]


@dataclass(frozen=True)
class EvalTableWriteRow:
    inputs: dict[str, Any]
    output: dict[str, Any] | None
    scores: dict[str, Any]


@dataclass(frozen=True)
class EvalTableWriteInput:
    name: str
    rows: list[EvalTableWriteRow]
    ncols: int
    log_mode: str


@dataclass(frozen=True)
class EvalTableWriteResult:
    marker: dict[str, Any]
    logged_id: str


class EvalTableWriter(Protocol):
    def bind(self, run: LocalRun, key: str, step: int | str) -> None: ...

    def validate_cell_value(self, value: Any, column: str | int) -> None: ...

    def write(self, value: EvalTableWriteInput) -> EvalTableWriteResult: ...


def create_eval_table_writer(
    backend: EvalTableBackend,
    *,
    unsupported_media_mode: media_adapters.UnsupportedMediaMode,
) -> EvalTableWriter:
    if backend == "weave":
        return WeaveEvalTableWriter(
            unsupported_media_mode=unsupported_media_mode,
        )
    if backend == "coreweave":
        return CoreWeaveEvalTableWriter()
    raise UsageError(
        f"Unsupported EvalTable backend {backend!r}; expected 'weave' or 'coreweave'."
    )


def _is_numpy_datetime64(value: Any) -> bool:
    np = wandb.util.np
    return np is not None and isinstance(value, np.datetime64)


def _is_datetime_like(value: Any) -> bool:
    return isinstance(value, datetime.date) or _is_numpy_datetime64(value)


def _normalize_numpy_datetime64(value: Any) -> datetime.datetime | None:
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
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
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
        del key, step
        weave_integration.init_weave(run.entity, run.project)

    def validate_cell_value(self, value: Any, column: str | int) -> None:
        media_adapters.validate_supported_value(
            value,
            column,
            unsupported_media_mode=self._unsupported_media_mode,
        )

    def write(self, value: EvalTableWriteInput) -> EvalTableWriteResult:
        from weave.evaluation.eval_imperative import EvaluationLogger

        evaluation = EvaluationLogger._create_with_meta(
            EVAL_TABLE_MARKER,
            name=value.name,
        )
        for row in value.rows:
            evaluation.log_example(
                inputs=self._normalize_mapping(row.inputs),
                output=(
                    self._normalize_mapping(row.output)
                    if row.output is not None
                    else None
                ),
                scores=self._normalize_mapping(row.scores),
            )

        evaluation.log_summary()
        # TODO: We should work with Weave on exposing a public evaluate_call_id()
        # instead of relying on this private field.
        evaluate_call_id = evaluation._evaluate_call.id
        return EvalTableWriteResult(
            marker={
                "_type": "eval-table",
                "ncols": value.ncols,
                "nrows": len(value.rows),
                "log_mode": value.log_mode,
                "evaluate_call_id": evaluate_call_id,
            },
            logged_id=evaluate_call_id,
        )

    def _normalize_mapping(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            column: self._normalize_value(item, column)
            for column, item in values.items()
        }

    def _normalize_value(self, value: Any, column: str) -> Any:
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
class _PreparedCoreWeaveWrite:
    dataset_fields: list[dict[str, str]]
    scorers: list[dict[str, str]]
    rows: list[dict[str, Any]]


class CoreWeaveEvalTableWriter:
    """Write an immutable EvalTable through the Evaluations service."""

    def __init__(self) -> None:
        self._project_id: str | None = None
        self._idempotency_scope: str | None = None

    def bind(self, run: LocalRun, key: str, step: int | str) -> None:
        if not run.project:
            raise UsageError("CoreWeave EvalTable logging requires a W&B project.")
        self._project_id = run.project
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

    def validate_cell_value(self, value: Any, column: str | int) -> None:
        self._normalize_primitive(value, str(column))

    def write(self, value: EvalTableWriteInput) -> EvalTableWriteResult:
        if self._project_id is None:
            raise UsageError("EvalTable must be logged with run.log().")

        prepared = self._prepare(value)
        base_url = os.environ.get(_COREWEAVE_BASE_URL_ENV)
        if not base_url:
            raise UsageError(
                f"Set {_COREWEAVE_BASE_URL_ENV} to the Evaluations service URL "
                "before logging a CoreWeave EvalTable."
            )

        client = self._create_client(base_url)
        try:
            created = client.eval_tables.create(
                self._project_id,
                name=value.name,
                idempotency_key=self._idempotency_key("create"),
            )
            client.eval_tables.create_columns(
                created.evaluation_id,
                project_id=self._project_id,
                dataset_fields=prepared.dataset_fields,
                scorers=prepared.scorers,
                idempotency_key=self._idempotency_key("columns"),
            )
            client.eval_tables.add_rows(
                created.evaluation_id,
                project_id=self._project_id,
                rows=prepared.rows,
                idempotency_key=self._idempotency_key("rows"),
            )
            version = client.eval_tables.create_version(
                created.evaluation_id,
                project_id=self._project_id,
                idempotency_key=self._idempotency_key("version"),
            )
        finally:
            client.close()

        _logger.debug(
            "CoreWeave EvalTable recorded evaluation_version_id=%s",
            version.evaluation_version_id,
        )

        return EvalTableWriteResult(
            marker={
                "_type": "eval-table",
                "backend": "coreweave",
                "schema_version": 1,
                "ncols": value.ncols,
                "nrows": len(value.rows),
                "log_mode": value.log_mode,
                "evaluation_id": created.evaluation_id,
                "evaluation_version_id": version.evaluation_version_id,
                "dataset_id": created.dataset_id,
                "dataset_version_id": version.dataset_version_id,
            },
            logged_id=version.evaluation_version_id,
        )

    def _prepare(self, value: EvalTableWriteInput) -> _PreparedCoreWeaveWrite:
        if not value.rows:
            raise UsageError("CoreWeave EvalTable logging requires at least one row.")
        if len(value.rows) > _MAX_ROWS:
            raise UsageError(
                f"CoreWeave EvalTable logging currently supports at most {_MAX_ROWS} "
                "rows per table."
            )

        dataset_field_types: dict[tuple[str, str], PrimitiveValueType] = {}
        dataset_field_order: list[tuple[str, str]] = []
        scorer_types: dict[str, PrimitiveValueType] = {}
        scorer_order: list[str] = []
        rows: list[dict[str, Any]] = []

        for row in value.rows:
            inputs = self._prepare_mapping(
                row.inputs,
                source="input",
                types=dataset_field_types,
                order=dataset_field_order,
            )
            output = (
                self._prepare_mapping(
                    row.output,
                    source="output",
                    types=dataset_field_types,
                    order=dataset_field_order,
                )
                if row.output is not None
                else None
            )
            scores = self._prepare_scores(
                row.scores,
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
                "CoreWeave EvalTable logging supports at most "
                f"{_MAX_DATASET_FIELDS} Dataset fields."
            )
        if len(scorer_order) > _MAX_SCORERS:
            raise UsageError(
                f"CoreWeave EvalTable logging supports at most {_MAX_SCORERS} "
                "score columns."
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
        self._validate_body_size("rows", {"rows": rows})
        return _PreparedCoreWeaveWrite(
            dataset_fields=dataset_fields,
            scorers=scorers,
            rows=rows,
        )

    def _prepare_mapping(
        self,
        values: dict[str, Any],
        *,
        source: Literal["input", "output"],
        types: dict[tuple[str, str], PrimitiveValueType],
        order: list[tuple[str, str]],
    ) -> dict[str, Any]:
        prepared: dict[str, Any] = {}
        for name, value in values.items():
            key = (source, name)
            if key not in order:
                order.append(key)
            normalized, value_type = self._normalize_primitive(value, name)
            if value_type is not None:
                types[key] = self._merge_type(name, types.get(key), value_type)
            prepared[name] = normalized
        return prepared

    def _prepare_scores(
        self,
        values: dict[str, Any],
        *,
        types: dict[str, PrimitiveValueType],
        order: list[str],
    ) -> dict[str, Any]:
        prepared: dict[str, Any] = {}
        for name, value in values.items():
            if name not in order:
                order.append(name)
            normalized, value_type = self._normalize_primitive(value, name)
            if value_type is not None:
                types[name] = self._merge_type(name, types.get(name), value_type)
            prepared[name] = normalized
        return prepared

    def _normalize_primitive(
        self,
        value: Any,
        column: str,
    ) -> tuple[Any, PrimitiveValueType | None]:
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
                return None, None
            if not math.isfinite(normalized):
                raise UsageError(
                    f"CoreWeave EvalTable column {column!r} contains a non-finite number."
                )
            return normalized, "number"
        if isinstance(value, str) or (np is not None and isinstance(value, np.str_)):
            return str(value), "string"

        raise UsageError(
            f"CoreWeave EvalTable column {column!r} contains unsupported value "
            f"type {type(value).__name__!r}; only primitive values are supported."
        )

    def _merge_type(
        self,
        column: str,
        existing: PrimitiveValueType | None,
        observed: PrimitiveValueType,
    ) -> PrimitiveValueType:
        if existing is None or existing == observed:
            return observed
        if {existing, observed} == {"integer", "number"}:
            return "number"
        raise UsageError(
            f"CoreWeave EvalTable column {column!r} mixes {existing!r} and "
            f"{observed!r} values."
        )

    def _validate_body_size(self, operation: str, body: dict[str, Any]) -> None:
        encoded = json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if len(encoded) >= _MAX_BATCH_BODY_BYTES:
            raise UsageError(
                f"CoreWeave EvalTable {operation} payload must be smaller than 16 MiB."
            )

    def _idempotency_key(self, operation: str) -> str:
        if self._idempotency_scope is None:
            raise UsageError("EvalTable must be logged with run.log().")
        return f"wandb-eval-table-v1-{self._idempotency_scope}-{operation}"

    def _create_client(self, base_url: str) -> Any:
        try:
            from coreweave_evaluations import CoreWeaveEvaluations
        except ImportError as exc:
            raise UsageError(
                "CoreWeave EvalTable logging requires the local Evaluations Python "
                "SDK. Install requirements-eval-table-coreweave-local.txt with uv."
            ) from exc

        return CoreWeaveEvaluations(base_url=base_url)
