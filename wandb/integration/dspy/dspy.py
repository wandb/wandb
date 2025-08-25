"""DSPy ↔ Weights & Biases integration."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
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

        with wandb.wandb_lib.telemetry.context(run=wandb.run) as tel:
            tel.feature.dspy_callback = True

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
                self._row_idx,
                *(self._temp_info_dict or {}).values(),
                float(outputs.score),
            )
            wandb.run.log(
                {"program_signature": self._program_table}, step=self._row_idx
            )
            self._row_idx += 1

    def _parse_results(
        self,
        results: list[tuple[dspy.Example, dspy.Prediction | dspy.Completions, bool]],
    ) -> list[dict[str, Any]]:
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

    def log_best_model(
        self,
        model: dspy.Module,
        *,
        save_program: bool = True,
        choice: str = "json",
        aliases: Sequence[str] = ("best", "latest"),
    ) -> None:
        """Save and log the best DSPy program as a W&B model artifact.

        Control saving with two options:
        - `save_program=True`: Save the whole program (architecture + state). A directory
          is typically produced and can be loaded with `dspy.load(dir)`.
        - `choice` selects the state file extension when `save_program=False`.

        Args:
            model (dspy.Module): The compiled/best DSPy program to persist.
            save_program (bool, optional): When True, save the entire program
                (architecture + state). When False, save state-only. Defaults to True.
            choice (str, optional): One of {"json", "pkl"}. Chooses the filename
                extension used for state-only saving. Ignored when
                `save_program=True`. Defaults to "json".
            aliases (Sequence[str], optional): Artifact aliases to assign
                when logging. Defaults to ("best", "latest").

        Examples:
            >>> # Whole-program saving (recommended for portability)
            >>> callback.log_best_model(best_program, save_program=True)

            >>> # State-only saving to JSON semantics
            >>> callback.log_best_model(best_program, save_program=False, choice="json")

            >>> # State-only saving to pickle semantics
            >>> callback.log_best_model(best_program, save_program=False, choice="pkl")
        """
        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before logging a DSPy model."
            )

        tmp_dir = tempfile.mkdtemp(prefix="dspy_program_")
        try:
            # Decide filename based on choice (used for state-only saving)
            normalized_choice = choice.lower().strip()
            if normalized_choice == "json":
                filename = "program.json"
            elif normalized_choice == "pkl":
                filename = "program.pkl"
            else:
                wandb.termwarn(
                    f"Unknown choice '{choice}'. Defaulting to JSON state file."
                )
                filename = "program.json"

            # Save per requested mode
            if save_program:
                # For whole-program saving, DSPy requires a directory path without a suffix
                model.save(tmp_dir, save_program=True)
                artifact_add_fn = ("dir", tmp_dir, "dspy_program")
            else:
                file_path = os.path.join(tmp_dir, filename)
                model.save(file_path, save_program=False)
                artifact_add_fn = ("file", file_path, f"dspy_program/{filename}")

            # Derive metadata to help discoverability in the UI
            info_dict = {}
            try:
                info_dict = self._extract_program_info(model) or {}
            except Exception as e:  # pragma: no cover - best effort metadata
                logger.debug("Failed to extract program info: %s", e)

            metadata = {
                "dspy_version": getattr(dspy, "__version__", "unknown"),
                "module_class": model.__class__.__name__,
                **info_dict,
            }

            # Create a stable-but-unique artifact name for the run
            run = wandb.run
            art_name = f"dspy-program-{run.id}"
            artifact = wandb.Artifact(name=art_name, type="model", metadata=metadata)

            # Include the saved program under a clear prefix inside the artifact
            kind, path, name = artifact_add_fn
            if kind == "dir":
                artifact.add_dir(path, name=name)
            else:
                artifact.add_file(path, name=name)

            logged = run.log_artifact(artifact, aliases=list(aliases))  # type: ignore[call-arg]

            # Optionally block until the upload finishes (if available)
            try:
                if hasattr(logged, "wait"):
                    logged.wait()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - non-critical
                pass

            # Store a small reference in the run summary for convenience
            try:
                ref = getattr(logged, "matched", None) or logged
                name = getattr(ref, "name", art_name)
                version = getattr(ref, "version", "")
                run.summary["best_model_artifact"] = f"{name}:{version}".rstrip(":")
            except Exception:  # pragma: no cover - best effort
                pass
        except Exception as e:
            logger.warning("Failed to log DSPy model artifact: %s", e)
        finally:
            if tmp_dir and os.path.isdir(tmp_dir):
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:  # pragma: no cover - cleanup best effort
                    pass
