"""DSPy ↔ Weights & Biases integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Optional

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

logger = logging.getLogger(__name__)


class WandbDSPyCallback(dspy.utils.BaseCallback):
    def __init__(self) -> None:
        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before instantiating WandbDSPyCallback()."
            )

        # TODO (ayulockin): add telemetry proto
        # Record feature usage for internal telemetry (optional but recommended).
        # with wandb.wandb_lib.telemetry.context(run=wandb.run) as tel:
        #     tel.feature.dspy = True

        self._did_log_config: bool = False
        self._temp_info_dict: dict[str, Any] = {}
        self._program_table: Optional[wandb.Table] = None
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
                        del serializable["devset"]
                    wandb.run.config.update(serializable)
            except Exception as e:
                logger.warning(
                    "Failed to build config snapshot from Evaluate instance: %s", e
                )
            finally:
                self._did_log_config = True

            # # Log devset as artifact if user requested it
            # if self.log_devset:
            #     devset_obj = inputs.get("devset", None)
            #     if devset_obj:
            #         dev_len = self._safe_len(devset_obj)
            #         if dev_len is not None:
            #             print("devset_length", dev_len)
            #             # TODO (ayulockin): log devset as artifact
            #             # Parse from stringified `Example` objects to `dict`s
            #             pass

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
        if isinstance(outputs, (int, float)) and exception is None:
            self._is_valid_score = True
            wandb.log({"score": float(outputs)}, step=self._row_idx)

        if self._program_table is None and self._is_valid_score:
            columns = ["step", *self._temp_info_dict.keys(), "score"]
            self._program_table = wandb.Table(columns=columns, log_mode="INCREMENTAL")

        if self._program_table is not None and self._is_valid_score:
            self._program_table.add_data(self._row_idx, *self._temp_info_dict.values(), float(outputs))
            wandb.run.log({"program_signature": self._program_table}, step=self._row_idx)
            self._row_idx += 1
