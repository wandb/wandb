"""DSPy ↔ Weights & Biases integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import wandb
import wandb.util

dspy = wandb.util.get_module(
    name="dspy",
    required=(
        "To use the W&B DSPy integration you need to have the `dspy` "
        "python package installed.  Install it with `uv pip install dspy`."
    ),
    lazy=True,  # Delay import until the first attribute access
)
assert dspy.__version__ >= "3.0.0", (
    "DSPy 3.0.0 or higher is required. You have " + dspy.__version__
)

logger = logging.getLogger(__name__)


class WandbDSPyCallback(dspy.utils.BaseCallback):
    def __init__(self, log_results: bool = True) -> None:
        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before instantiating WandbDSPyCallback()."
            )
        
        self.log_results = log_results

        # TODO (ayulockin): add telemetry proto
        # Record feature usage for internal telemetry (optional but recommended).
        # with wandb.wandb_lib.telemetry.context(run=wandb.run) as tel:
        #     tel.feature.dspy = True
        self._did_log_config: bool = False
        self._temp_info_dict: dict[str, Any] = {}
        self._program_table: wandb.Table | None = None
        self._is_valid_score: bool = False
        self._row_idx: int = 0

    def _flatten_dict(
        self, nested: Any, parent_key: str = "", sep: str = "."
    ) -> dict[str, Any]:
        flat: dict[str, Any] = {}

        def _walk(obj: Any, base: str) -> None:
            if isinstance(obj, Mapping):
                for k, v in obj.items():
                    new_key = f"{base}{sep}{k}" if base else str(k)
                    _walk(v, new_key)
            elif isinstance(obj, Sequence) and not isinstance(
                obj, (str, bytes, bytearray)
            ):
                for idx, v in enumerate(obj):
                    new_key = f"{base}{sep}{idx}" if base else str(idx)
                    _walk(v, new_key)
            else:
                # Base can be empty only if the top-level is a scalar; guard against that.
                key = base if base else ""
                if key:
                    flat[key] = obj

        _walk(nested, parent_key)
        return flat

    def _extract_fields(self, fields: list[dict[str, Any]]) -> dict[str, str]:
        return {k: str(v) for k, v in fields.items()}

    def _extract_program_info(self, program_obj: Any) -> dict[str, Any]:
        info_dict = {}

        if program_obj is None:
            return info_dict

        try:
            from dspy.predict.predict import Predict

            sig = next(
                param.signature
                for _, param in program_obj.named_parameters()
                if isinstance(param, Predict)
            )

            if getattr(sig, "signature", None):
                info_dict["signature"] = sig.signature
            if getattr(sig, "instructions", None):
                info_dict["instructions"] = sig.instructions
            if getattr(sig, "input_fields", None):
                input_fields = sig.input_fields
                info_dict["input_fields"] = self._extract_fields(input_fields)
            if getattr(sig, "output_fields", None):
                output_fields = sig.output_fields
                info_dict["output_fields"] = self._extract_fields(output_fields)

            return self._flatten_dict(info_dict)
        except Exception as e:
            logger.warning(
                "Failed to extract program info from Evaluate instance: %s", e
            )
            return info_dict

    def on_evaluate_start(
        self,
        call_id: str,
        instance: Any,
        inputs: dict[str, Any],
    ) -> None:
        if not self._did_log_config:
            try:
                instance_vars = vars(instance) if hasattr(instance, "__dict__") else {}
                serializable = {
                    k: v for k, v in instance_vars.items() if not k.startswith("_")
                }
                if serializable:
                    if "devset" in serializable:
                        # we don't want to log the devset in the config
                        del serializable["devset"]
                    wandb.run.config.update(serializable)
            except Exception as e:
                logger.warning(
                    "Failed to build config snapshot from Evaluate instance: %s", e
                )
            finally:
                self._did_log_config = True

        # 2) Build/append program signature tables from the 'program' input
        program_obj = inputs.get("program", None)
        if program_obj:
            self._temp_info_dict = self._extract_program_info(program_obj)
        else:
            self._temp_info_dict = None

    def on_evaluate_end(
        self,
        call_id: str,
        outputs: Any | None,
        exception: Exception | None = None,
    ) -> None:
        if exception is None and outputs is not None:
            assert isinstance(outputs, dspy.evaluate.evaluate.EvaluationResult)
            wandb.log({"score": float(outputs.score)}, step=self._row_idx)

        # Log the predictions as a separate table for each eval end.
        if self.log_results and exception is None and outputs is not None:
            rows = self._parse_results(outputs.results)
            if rows:
                self._log_predictions_table(rows)

        if self._program_table is None:
            columns = ["step", *(self._temp_info_dict or {}).keys(), "score"]
            self._program_table = wandb.Table(columns=columns, log_mode="INCREMENTAL")

        if self._program_table is not None:
            self._program_table.add_data(
                self._row_idx, *(self._temp_info_dict or {}).values(), float(outputs.score)
            )
            wandb.run.log(
                {"program_signature": self._program_table}, step=self._row_idx
            )
            self._row_idx += 1

    def _parse_results(self, results: list[tuple[dspy.Example, dspy.Prediction | dspy.Completions, bool]]) -> list[dict[str, Any]]:
        """
        Convert DSPy evaluation results into row data suitable for W&B Tables.

        Args:
            results (list[tuple[dspy.Example, dspy.Prediction | dspy.Completions, bool]]):
                List of (example, prediction, is_correct) tuples from DSPy Evaluate.

        Returns:
            list[dict[str, Any]]: Rows where each row is a dict of column -> value.

        Examples:
            >>> # Assuming you have a list of DSPy results named `results`
            >>> # cb = WandbDSPyCallback(); rows = cb._parse_results(results)  # doctest: +SKIP
        """
        _rows: list[dict[str, Any]] = []
        for example, prediction, is_correct in results:
            example_dict = example.toDict()
            if isinstance(prediction, dspy.Prediction):
                prediction_dict = prediction.toDict()
            elif isinstance(prediction, dspy.Completions):
                # Ensure serializable structure
                try:
                    prediction_dict = prediction.toDict()  # type: ignore[attr-defined]
                except Exception:
                    prediction_dict = list(getattr(prediction, "items", lambda: [])())
            else:
                wandb.termwarn(f"Unsupported prediction type: {type(prediction)}")
                continue

            row: dict[str, Any] = {
                "example": example_dict,
                "prediction": prediction_dict,
                "is_correct": is_correct,
            }
            _rows.append(row)

        return _rows

    def _log_predictions_table(self, rows: list[dict[str, Any]]) -> None:
        """
        Log predictions as a W&B Table for the current evaluation step.

        Args:
            rows (list[dict[str, Any]]): List of dict rows where keys are column names.

        Returns:
            None

        Examples:
            >>> cb = WandbDSPyCallback(log_results=False)  # doctest: +SKIP
            >>> cb._row_idx = 0  # doctest: +SKIP
            >>> cb._log_predictions_table([{"example": {"q": "..."}, "prediction": {"a": "..."}, "is_correct": True}])  # doctest: +SKIP
        """
        if not rows:
            return

        # Derive columns from row dict keys, preserving insertion order and handling missing keys.
        seen: set[str] = set()
        columns: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    seen.add(key)
                    columns.append(key)

        # Convert dict rows to list rows matching the derived columns
        data: list[list[Any]] = [[row.get(col) for col in columns] for row in rows]

        preds_table = wandb.Table(columns=columns, data=data, log_mode="IMMUTABLE")
        wandb.run.log({f"predictions_{self._row_idx}": preds_table}, step=self._row_idx)
