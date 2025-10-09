"""DSPy ↔ Weights & Biases integration."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import wandb
import wandb.util
from wandb.sdk.wandb_run import Run

dspy = wandb.util.get_module(
    name="dspy",
    required=(
        "To use the W&B DSPy integration you need to have the `dspy` "
        "python package installed.  Install it with `uv pip install dspy`."
    ),
    lazy=False,
)
if dspy is not None:
    assert dspy.__version__ >= "3.0.0", (
        "DSPy 3.0.0 or higher is required. You have " + dspy.__version__
    )


logger = logging.getLogger(__name__)


def _flatten_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten a list of nested row dicts into flat key/value dicts.

    Args:
        rows (list[dict[str, Any]]): List of nested dictionaries to flatten.

    Returns:
        list[dict[str, Any]]: List of flattened dictionaries.

    """

    def _flatten(
        d: dict[str, Any], parent_key: str = "", sep: str = "."
    ) -> dict[str, Any]:
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(_flatten(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    return [_flatten(row) for row in rows]


class WandbDSPyCallback(dspy.utils.BaseCallback):
    """W&B callback for tracking DSPy evaluation and optimization.

    This callback logs evaluation scores, per-step predictions (optional), and
    a table capturing the DSPy program signature over time. It can also save
    the best program as a W&B Artifact for reproducibility.

    Examples:
        Basic usage within DSPy settings:

        ```python
        import dspy
        import wandb
        from wandb.integration.dspy import WandbDSPyCallback

        with wandb.init(project="dspy-optimization") as run:
            dspy.settings.callbacks.append(WandbDSPyCallback(run=run))
            # Run your DSPy optimization/evaluation
        ```
    """

    def __init__(self, log_results: bool = True, run: Run | None = None) -> None:
        """Initialize the callback.

        Args:
            log_results (bool): Whether to log per-evaluation prediction tables.
            run (Run | None): Optional W&B run to use. Defaults to the
                current global run if available.

        Raises:
            wandb.Error: If no active run is provided or found.
        """
        # If no run is provided, use the current global run if available.
        if run is None:
            if wandb.run is None:
                raise wandb.Error(
                    "You must call `wandb.init()` before instantiating WandbDSPyCallback()."
                )
            run = wandb.run

        self.log_results = log_results

        with wandb.wandb_lib.telemetry.context(run=run) as tel:
            tel.feature.dspy_callback = True

        self._run = run
        self._did_log_config: bool = False
        self._program_info: dict[str, Any] = {}
        self._program_table: wandb.Table | None = None
        self._row_idx: int = 0

    def _flatten_dict(
        self, nested: Any, parent_key: str = "", sep: str = "."
    ) -> dict[str, Any]:
        """Recursively flatten arbitrarily nested mappings and sequences.

        Args:
            nested (Any): Nested structure of mappings/lists to flatten.
            parent_key (str): Prefix to prepend to keys in the flattened output.
            sep (str): Key separator for nested fields.

        Returns:
            dict[str, Any]: Flattened dictionary representation.
        """
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
        """Convert signature fields to a flat mapping of strings.

        Note:
            The input is expected to be a dict-like mapping from field names to
            field metadata. Values are stringified for logging.

        Args:
            fields (list[dict[str, Any]]): Mapping of field name to metadata.

        Returns:
            dict[str, str]: Mapping of field name to string value.
        """
        return {k: str(v) for k, v in fields.items()}

    def _extract_program_info(self, program_obj: Any) -> dict[str, Any]:
        """Extract signature-related info from a DSPy program.

        Attempts to read the program signature, instructions, input and output
        fields from a DSPy `Predict` parameter if available.

        Args:
            program_obj (Any): DSPy program/module instance.

        Returns:
            dict[str, Any]: Flattened dictionary of signature metadata.
        """
        info_dict = {}

        if program_obj is None:
            return info_dict

        try:
            sig = next(
                param.signature
                for _, param in program_obj.named_parameters()
                if isinstance(param, dspy.Predict)
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
        """Handle start of a DSPy evaluation call.

        Logs non-private fields from the evaluator instance to W&B config and
        captures program signature info for later logging.

        Args:
            call_id (str): Unique identifier for the evaluation call.
            instance (Any): The evaluation instance (e.g., `dspy.Evaluate`).
            inputs (dict[str, Any]): Inputs passed to the evaluation (may
                include a `program` key with the DSPy program).
        """
        if not self._did_log_config:
            instance_vars = vars(instance) if hasattr(instance, "__dict__") else {}
            serializable = {
                k: v for k, v in instance_vars.items() if not k.startswith("_")
            }
            if "devset" in serializable:
                # we don't want to log the devset in the config
                del serializable["devset"]

            self._run.config.update(serializable)
            self._did_log_config = True

        # 2) Build/append program signature tables from the 'program' inputs
        if program_obj := inputs.get("program"):
            self._program_info = self._extract_program_info(program_obj)

    def on_evaluate_end(
        self,
        call_id: str,
        outputs: Any | None,
        exception: Exception | None = None,
    ) -> None:
        """Handle end of a DSPy evaluation call.

        If available, logs a numeric `score` metric and (optionally) per-step
        prediction tables. Always appends a row to the program-signature table.

        Args:
            call_id (str): Unique identifier for the evaluation call.
            outputs (Any | None): Evaluation outputs; supports
                `dspy.evaluate.evaluate.EvaluationResult`.
            exception (Exception | None): Exception raised during evaluation, if any.
        """
        # The `BaseCallback` does not define the interface for the `outputs` parameter,
        # Currently, we know of `EvaluationResult` which is a subclass of `dspy.Prediction`.
        # We currently support this type and will warn the user if a different type is passed.
        score: float | None = None
        if exception is None:
            if isinstance(outputs, dspy.evaluate.evaluate.EvaluationResult):
                # log the float score as a wandb metric
                score = outputs.score
                wandb.log({"score": float(score)}, step=self._row_idx)

                # Log the predictions as a separate table for each eval end.
                # We know that results if of type `list[tuple["dspy.Example", "dspy.Example", Any]]`
                results = outputs.results
                if self.log_results:
                    rows = self._parse_results(results)
                    if rows:
                        self._log_predictions_table(rows)
            else:
                wandb.termwarn(
                    f"on_evaluate_end received unexpected outputs type: {type(outputs)}. "
                    "Expected dspy.evaluate.evaluate.EvaluationResult; skipping logging score and `log_results`."
                )
        else:
            wandb.termwarn(
                f"on_evaluate_end received exception: {exception}. "
                "Skipping logging score and `log_results`."
            )

        # Log the program signature iteratively
        if self._program_table is None:
            columns = ["step", *self._program_info.keys()]
            if isinstance(score, float):
                columns.append("score")
            self._program_table = wandb.Table(columns=columns, log_mode="INCREMENTAL")

        if self._program_table is not None:
            values = list(self._program_info.values())
            if isinstance(score, float):
                values.append(score)

            self._program_table.add_data(
                self._row_idx,
                *values,
            )
            self._run.log(
                {"program_signature": self._program_table}, step=self._row_idx
            )

        self._row_idx += 1

    def _parse_results(
        self,
        results: list[tuple[dspy.Example, dspy.Prediction | dspy.Completions, bool]],
    ) -> list[dict[str, Any]]:
        """Normalize evaluation results into serializable row dicts.

        Args:
            results (list[tuple]): Sequence of `(example, prediction, is_correct)`
                tuples from DSPy evaluation.

        Returns:
            list[dict[str, Any]]: Rows with `example`, `prediction`, `is_correct`.
        """
        _rows: list[dict[str, Any]] = []
        for example, prediction, is_correct in results:
            if isinstance(prediction, dspy.Prediction):
                prediction_dict = prediction.toDict()
            if isinstance(prediction, dspy.Completions):
                prediction_dict = prediction.items()

            row: dict[str, Any] = {
                "example": example.toDict(),
                "prediction": prediction_dict,
                "is_correct": is_correct,
            }
            _rows.append(row)

        return _rows

    def _log_predictions_table(self, rows: list[dict[str, Any]]) -> None:
        """Log a W&B Table of predictions for the current evaluation step.

        Args:
            rows (list[dict[str, Any]]): Prediction rows to log.
        """
        rows = _flatten_rows(rows)
        columns = list(rows[0].keys())

        data: list[list[Any]] = [list(row.values()) for row in rows]

        preds_table = wandb.Table(columns=columns, data=data, log_mode="IMMUTABLE")
        self._run.log({f"predictions_{self._row_idx}": preds_table}, step=self._row_idx)

    def log_best_model(
        self,
        model: dspy.Module,
        *,
        save_program: bool = True,
        save_dir: str | None = None,
        filetype: Literal["json", "pkl"] = "json",
        aliases: Sequence[str] = ("best", "latest"),
        artifact_name: str = "dspy-program",
    ) -> None:
        """Save and log the best DSPy program as a W&B Artifact.

        You can choose to save the full program (architecture + state) or only
        the state to a single file (JSON or pickle).

        Args:
            model (dspy.Module): DSPy module to save.
            save_program (bool): Save full program directory if True; otherwise
                save only the state file. Defaults to `True`.
            save_dir (str): Directory to store program files before logging. Defaults to a
                subdirectory `dspy_program` within the active run's files directory
                (i.e., `wandb.run.dir`).
            filetype (Literal["json", "pkl"]): State file format when
                `save_program` is False. Defaults to `json`.
            aliases (Sequence[str]): Aliases for the logged Artifact version. Defaults to `("best", "latest")`.
            artifact_name (str): Base name for the Artifact. Defaults to `dspy-program`.

        Examples:
            Save the complete program and add aliases:

            ```python
            callback.log_best_model(
                optimized_program, save_program=True, aliases=("best", "production")
            )
            ```

            Save only the state as JSON:

            ```python
            callback.log_best_model(
                optimized_program, save_program=False, filetype="json"
            )
            ```
        """
        # Derive metadata to help discoverability in the UI
        info_dict = self._extract_program_info(model)
        metadata = {
            "dspy_version": getattr(dspy, "__version__", "unknown"),
            "module_class": model.__class__.__name__,
            **info_dict,
        }
        artifact = wandb.Artifact(
            name=f"{artifact_name}-{self._run.id}",
            type="model",
            metadata=metadata,
        )

        # Resolve and normalize the save directory in a cross-platform way
        if save_dir is None:
            save_dir = os.path.join(self._run.dir, "dspy_program")
        save_dir = os.path.normpath(save_dir)

        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as exc:
            wandb.termwarn(
                f"Could not create or access directory '{save_dir}': {exc}. Skipping artifact logging."
            )
            return
        # Save per requested mode
        if save_program:
            model.save(save_dir, save_program=True)
            artifact.add_dir(save_dir)
        else:
            filename = f"program.{filetype}"
            file_path = os.path.join(save_dir, filename)
            model.save(file_path, save_program=False)
            artifact.add_file(file_path)

        self._run.log_artifact(artifact, aliases=list(aliases))
