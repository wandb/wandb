"""DSPy ↔ Weights & Biases integration."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


class WandbDSPyCallback(dspy.utils.BaseCallback):
    def __init__(self) -> None:
        # Safety check – we need a run to stream data into.
        if wandb.run is None:
            raise wandb.Error(
                "You must call `wandb.init()` before instantiating WandbDSPyCallback()."
            )

        # Record feature usage for internal telemetry (optional but recommended).
        with wandb.wandb_lib.telemetry.context(run=wandb.run) as tel:
            tel.feature.dspy = True

    def on_evaluate_start(
        self,
        call_id: str,
        instance: Any,
        inputs: dict[str, Any],
    ) -> None:
        """Invoked by DSPy *before* an evaluation round starts."""
        logger.debug("on_evaluate_start", call_id, instance, inputs)

    def on_evaluate_end(
        self,
        call_id: str,
        outputs: Any | None,
        exception: Exception | None = None,
    ) -> None:
        logger.debug("on_evaluate_end", call_id, outputs, exception)
